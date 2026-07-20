(function () {
  let dismissTimer;

  function attachBuildToast() {
    const toast = document.getElementById("build-message");
    if (!toast || toast.dataset.toastObserverAttached === "true") return;

    toast.dataset.toastObserverAttached = "true";
    const showToast = () => {
      if (!toast.textContent.trim()) return;
      toast.classList.remove("toast-visible");
      void toast.offsetWidth;
      toast.classList.add("toast-visible");
      window.clearTimeout(dismissTimer);
      dismissTimer = window.setTimeout(() => toast.classList.remove("toast-visible"), 4500);
    };

    new MutationObserver(showToast).observe(toast, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    showToast();
  }

  const pageObserver = new MutationObserver(attachBuildToast);
  pageObserver.observe(document.documentElement, {childList: true, subtree: true});
  document.addEventListener("DOMContentLoaded", attachBuildToast);
  window.addEventListener("load", attachBuildToast);
  attachBuildToast();
})();
