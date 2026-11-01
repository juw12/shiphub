/* Runs before first paint so the page never flashes the wrong theme. */
(function () {
  var saved = null;
  try {
    saved = localStorage.getItem("shiphub.theme");
  } catch (error) {
    saved = null;
  }
  var prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.theme = saved || (prefersDark ? "dark" : "light");
})();
