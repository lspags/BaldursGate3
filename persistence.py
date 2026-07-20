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
<form method="post"><input type="hidden" name="csrf_token" value="{{ csrf_token }}">
<label>Email<input type="email" name="email" maxlength="320" required autocomplete="email"></label>
<label>Password<input type="password" name="password" minlength="10" required autocomplete="{{ autocomplete }}"></label>
<button type="submit">{{ title }}</button></form><p>{{ switch_text }} <a href="{{ switch_url }}">{{ switch_label }}</a></p>
<p><a href="{{ home_url }}">Continue as guest</a></p></main></body></html>
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
        return render_template_string(
            AUTH_PAGE, title=title, error=error, csrf_token=_csrf_token(),
            autocomplete="new-password" if registering else "current-password",
            switch_text="Already registered?" if registering else "Need an account?",
            switch_url=url_for("login") if registering else url_for("register"),
            switch_label="Sign in" if registering else "Create one", home_url="./",
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
        return redirect("./")

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
        return redirect("./")

    @server.route("/logout")
    def logout():
        logout_user()
        return redirect("./")


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
