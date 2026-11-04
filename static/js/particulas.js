/* Partículas flotantes de fondo para todas las páginas */
(function () {
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  var canvas = document.createElement("canvas");
  canvas.setAttribute("aria-hidden", "true");
  canvas.style.cssText =
    "position:fixed;top:0;left:0;width:100vw;height:100vh;z-index:-1;pointer-events:none;";

  function iniciar() {
    document.body.insertBefore(canvas, document.body.firstChild);
    var ctx = canvas.getContext("2d");
    var particulas = [];

    function ajustar() {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    }
    ajustar();
    window.addEventListener("resize", ajustar);

    var total = window.innerWidth < 700 ? 25 : 40;
    for (var i = 0; i < total; i++) {
      particulas.push({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 2.5 + 1,
        vx: (Math.random() - 0.5) * 0.5,
        vy: (Math.random() - 0.5) * 0.5,
        a: Math.random() * 0.5 + 0.2
      });
    }

    function animar() {
      if (!document.hidden) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        for (var j = 0; j < particulas.length; j++) {
          var p = particulas[j];
          p.x += p.vx;
          p.y += p.vy;
          if (p.x < 0) p.x = canvas.width;
          if (p.x > canvas.width) p.x = 0;
          if (p.y < 0) p.y = canvas.height;
          if (p.y > canvas.height) p.y = 0;
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(255, 255, 255, " + p.a + ")";
          ctx.fill();
        }
      }
      requestAnimationFrame(animar);
    }
    animar();
  }

  if (document.body) iniciar();
  else document.addEventListener("DOMContentLoaded", iniciar);
})();
