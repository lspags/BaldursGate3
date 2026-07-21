"""Optional account authentication and database persistence for Posit."""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timezone
from html import escape

from flask import Flask, abort, redirect, render_template_string, request, session, url_for
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from sqlalchemy import JSON, DateTime, ForeignKey, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from werkzeug.security import check_password_hash, generate_password_hash


AUTH_ENABLED = os.getenv("BG3_AUTH_ENABLED", "1").lower() not in {"0", "false", "no"}
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///bg3_published_local.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix("postgres://")
elif DATABASE_URL.startswith("postgresql://") and "+psycopg" not in DATABASE_URL:
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.removeprefix("postgresql://")


class Base(DeclarativeBase):
    pass


class User(UserMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    builds: Mapped[list["Build"]] = relationship(back_populates="owner", cascade="all, delete-orphan")


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    build_data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    owner: Mapped[User] = relationship(back_populates="builds")


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    team_data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


class SharedBuild(Base):
    __tablename__ = "shared_builds"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    build_id: Mapped[int] = mapped_column(ForeignKey("builds.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    snapshot: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
login_manager = LoginManager()


AUTH_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ title }} · BG3 Character Builder</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#151416;color:#eee5d4;font:16px system-ui,sans-serif}
main{width:min(420px,calc(100% - 40px));padding:30px;background:#242126;border:1px solid #9f773d;border-radius:10px;box-shadow:0 18px 60px #0008}
h1{margin-top:0;color:#e5c276;font-family:Georgia,serif}label{display:grid;gap:6px;margin:16px 0;color:#d8c6a5}
input{padding:12px;background:#121114;color:#fff;border:1px solid #755d3a;border-radius:5px}button{width:100%;padding:12px;background:#7e2629;color:#fff;border:1px solid #d1ad61;border-radius:5px;font-weight:700;cursor:pointer}
a{color:#e5c276}.error{padding:10px;background:#6e2428;border-radius:5px}</style></head>
<body><main><h1>{{ title }}</h1>{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><input type="hidden" name="next" value="{{ next_url }}">
<label>Email<input type="email" name="email" maxlength="320" required autocomplete="email"></label>
<label>Password<input type="password" name="password" minlength="10" required autocomplete="{{ autocomplete }}"></label>
<button type="submit">{{ title }}</button></form><p>{{ switch_text }} <a href="{{ switch_url }}">{{ switch_label }}</a></p>
<p><a href="{{ home_url }}">Continue as guest</a></p></main></body></html>
"""

SHARED_BUILD_PAGE = """
<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ shared.name }} · Shared BG3 Build</title><style>
body{margin:0;background:#151416;color:#eee5d4;font:15px system-ui,sans-serif}main{width:min(1100px,calc(100% - 36px));margin:35px auto 70px}header,.card{padding:22px;background:#242126;border:1px solid #9f773d;border-radius:9px}header{margin-bottom:16px}h1,h2{color:#e5c276;font-family:Georgia,serif}h1{margin:4px 0}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.card h2{margin-top:0;font-size:1.05rem}.tags{display:flex;flex-wrap:wrap;gap:7px}.tags span{padding:5px 8px;background:#151416;border:1px solid #755d3a;border-radius:999px}.abilities{display:grid;grid-template-columns:repeat(6,1fr);gap:7px}.abilities div{text-align:center;padding:10px;background:#151416;border-radius:5px}.abilities strong{display:block;color:#e5c276;font-size:1.2rem}button{padding:11px 15px;color:#fff;background:#7e2629;border:1px solid #d1ad61;border-radius:5px;font-weight:700;cursor:pointer}a{color:#e5c276}.actions{display:flex;gap:12px;align-items:center;margin-top:16px}@media(max-width:650px){.grid{grid-template-columns:1fr}.abilities{grid-template-columns:repeat(3,1fr)}}
</style></head><body><main><header><small>READ-ONLY SHARED BUILD</small><h1>{{ shared.name }}</h1><p>{{ payload.character_name or 'Unnamed Adventurer' }} · {{ payload.race or 'No race' }}{% if payload.subrace %} / {{ payload.subrace }}{% endif %} · {{ payload.background or 'No background' }}</p>
<div class="actions">{% if signed_in %}<form method="post" action="{{ duplicate_url }}"><input type="hidden" name="csrf_token" value="{{ csrf_token }}"><button type="submit">Duplicate to My Builds</button></form>{% else %}<a href="{{ login_url }}">Sign in to duplicate this build</a>{% endif %}<a href="{{ home_url }}">Open Character Builder</a></div></header>
<div class="grid"><section class="card"><h2>Classes</h2><div class="tags">{% for value in classes %}<span>{{ value }}</span>{% else %}<span>None</span>{% endfor %}</div></section>
<section class="card"><h2>Ability Scores</h2><div class="abilities">{% for name,value in abilities.items() %}<div><small>{{ name[:3]|upper }}</small><strong>{{ value }}</strong></div>{% endfor %}</div></section>
<section class="card"><h2>Equipment</h2><div class="tags">{% for value in equipment %}<span>{{ value }}</span>{% else %}<span>None</span>{% endfor %}</div></section>
<section class="card"><h2>Feats</h2><div class="tags">{% for value in feats %}<span>{{ value }}</span>{% else %}<span>None</span>{% endfor %}</div></section>
<section class="card"><h2>Selected Spells</h2><div class="tags">{% for value in spells %}<span>{{ value }}</span>{% else %}<span>None</span>{% endfor %}</div></section>
<section class="card"><h2>Build Details</h2><p>All leveling choices, conditional selections, act loadouts, and item checklist state are included when this build is duplicated.</p></section></div></main></body></html>
"""


def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _valid_csrf() -> bool:
    return secrets.compare_digest(session.get("csrf_token", ""), request.form.get("csrf_token", ""))


def init_persistence(server: Flask) -> None:
    if not AUTH_ENABLED:
        return
    server.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
    server.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    if os.getenv("POSIT_PRODUCT") == "CONNECT":
        server.config["SESSION_COOKIE_SECURE"] = True
    Base.metadata.create_all(engine)
    login_manager.init_app(server)

    @login_manager.user_loader
    def load_user(user_id: str):
        with SessionLocal() as db:
            return db.get(User, int(user_id)) if user_id.isdigit() else None

    def auth_page(title, error=None):
        registering = title == "Create account"
        next_url = request.values.get("next", "")
        return render_template_string(
            AUTH_PAGE, title=title, error=error, csrf_token=_csrf_token(),
            autocomplete="new-password" if registering else "current-password",
            switch_text="Already registered?" if registering else "Need an account?",
            switch_url=(url_for("login", next=next_url) if registering else url_for("register", next=next_url)),
            switch_label="Sign in" if registering else "Create one", home_url="./",
            next_url=next_url,
        )

    @server.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "GET":
            return auth_page("Create account")
        if not _valid_csrf():
            abort(400)
        email, password = request.form.get("email", "").strip().lower(), request.form.get("password", "")
        if len(password) < 10:
            return auth_page("Create account", "Use a password with at least 10 characters."), 400
        with SessionLocal() as db:
            if db.scalar(select(User).where(User.email == email)):
                return auth_page("Create account", "An account already exists for that email."), 409
            user = User(email=email, password_hash=generate_password_hash(password, method="scrypt"))
            db.add(user); db.commit(); login_user(user)
        next_url = request.form.get("next", "")
        return redirect(next_url if next_url.startswith("/") and not next_url.startswith("//") else "./")

    @server.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return auth_page("Sign in")
        if not _valid_csrf():
            abort(400)
        email, password = request.form.get("email", "").strip().lower(), request.form.get("password", "")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == email))
            if not user or not check_password_hash(user.password_hash, password):
                return auth_page("Sign in", "Invalid email or password."), 401
            login_user(user, remember=True)
        next_url = request.form.get("next", "")
        return redirect(next_url if next_url.startswith("/") and not next_url.startswith("//") else "./")

    @server.route("/logout")
    def logout():
        logout_user()
        return redirect("./")

    @server.route("/share/<token>")
    def shared_build_page(token):
        shared = get_shared_build(token)
        if not shared:
            abort(404)
        payload = shared["snapshot"]
        classes = [value for value in payload.get("classes", []) if value]
        equipment = [value.split("|")[-1] for value in (payload.get("equipment") or {}).values() if value]
        spells = []
        for record in payload.get("spell_choices") or []:
            value = record.get("value")
            spells.extend(value if isinstance(value, list) else ([value] if value else []))
        feats = [value for value in payload.get("feats", []) if value]
        abilities = (payload.get("abilities") or {}).get("scores", {})
        return render_template_string(SHARED_BUILD_PAGE, shared=shared, payload=payload, classes=classes,
                                      equipment=equipment, spells=list(dict.fromkeys(spells)), feats=feats,
                                      abilities=abilities, signed_in=current_user.is_authenticated,
                                      csrf_token=_csrf_token(), login_url=url_for("login", next=request.path), home_url="../..",
                                      duplicate_url=url_for("duplicate_shared_build_route", token=token))

    @server.route("/share/<token>/duplicate", methods=["POST"])
    def duplicate_shared_build_route(token):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        if not _valid_csrf():
            abort(400)
        build_id = duplicate_shared_build(int(current_user.id), token)
        if not build_id:
            abort(404)
        return redirect("../../")


def user_identity() -> tuple[int | None, str | None]:
    if not AUTH_ENABLED or not current_user.is_authenticated:
        return None, None
    return int(current_user.id), str(current_user.email)


def list_builds(user_id: int) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(Build).where(Build.user_id == user_id).order_by(Build.updated_at.desc())).all()
        return [{"id": row.id, "name": row.name, "updated_at": row.updated_at.isoformat()} for row in rows]


def save_build(user_id: int, name: str, payload: dict, build_id: int | None = None) -> int:
    with SessionLocal() as db:
        row = db.scalar(select(Build).where(Build.id == build_id, Build.user_id == user_id)) if build_id else None
        if row:
            row.name, row.build_data, row.updated_at = name, payload, datetime.now(timezone.utc)
        else:
            row = Build(user_id=user_id, name=name, build_data=payload)
            db.add(row)
        db.commit()
        return row.id


def load_build(user_id: int, build_id: int) -> dict | None:
    with SessionLocal() as db:
        row = db.scalar(select(Build).where(Build.id == build_id, Build.user_id == user_id))
        return dict(row.build_data) if row else None


def delete_build(user_id: int, build_id: int) -> bool:
    with SessionLocal() as db:
        row = db.scalar(select(Build).where(Build.id == build_id, Build.user_id == user_id))
        if not row:
            return False
        db.delete(row); db.commit()
        return True


def list_teams(user_id: int) -> list[dict]:
    with SessionLocal() as db:
        rows = db.scalars(select(Team).where(Team.user_id == user_id).order_by(Team.updated_at.desc())).all()
        return [{"id": row.id, "name": row.name, "team_data": dict(row.team_data)} for row in rows]


def save_team(user_id: int, name: str, payload: dict, team_id: int | None = None) -> int:
    with SessionLocal() as db:
        row = db.scalar(select(Team).where(Team.id == team_id, Team.user_id == user_id)) if team_id else None
        if row:
            row.name, row.team_data, row.updated_at = name, payload, datetime.now(timezone.utc)
        else:
            row = Team(user_id=user_id, name=name, team_data=payload)
            db.add(row)
        db.commit()
        return row.id


def delete_team(user_id: int, team_id: int) -> bool:
    with SessionLocal() as db:
        row = db.scalar(select(Team).where(Team.id == team_id, Team.user_id == user_id))
        if not row:
            return False
        db.delete(row); db.commit()
        return True


def create_build_share(user_id: int, build_id: int) -> str | None:
    with SessionLocal() as db:
        build = db.scalar(select(Build).where(Build.id == build_id, Build.user_id == user_id))
        if not build:
            return None
        shared = db.scalar(select(SharedBuild).where(SharedBuild.build_id == build_id, SharedBuild.owner_id == user_id))
        if shared:
            shared.name, shared.snapshot = build.name, dict(build.build_data)
        else:
            shared = SharedBuild(token=secrets.token_urlsafe(32), owner_id=user_id, build_id=build_id,
                                 name=build.name, snapshot=dict(build.build_data))
            db.add(shared)
        db.commit()
        return shared.token


def revoke_build_share(user_id: int, build_id: int) -> bool:
    with SessionLocal() as db:
        shared = db.scalar(select(SharedBuild).where(SharedBuild.build_id == build_id, SharedBuild.owner_id == user_id))
        if not shared:
            return False
        db.delete(shared); db.commit()
        return True


def get_shared_build(token: str) -> dict | None:
    with SessionLocal() as db:
        shared = db.scalar(select(SharedBuild).where(SharedBuild.token == token))
        return {"token": shared.token, "name": shared.name, "snapshot": dict(shared.snapshot)} if shared else None


def duplicate_shared_build(user_id: int, token: str) -> int | None:
    shared = get_shared_build(token)
    if not shared:
        return None
    return save_build(user_id, f"Copy of {shared['name']}"[:120], dict(shared["snapshot"]))
