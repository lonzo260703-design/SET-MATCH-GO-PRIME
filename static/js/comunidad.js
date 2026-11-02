// Like sin recargar la página
(function () {
  const meta = document.querySelector('meta[name="csrf-token"]');
  document.querySelectorAll('button.com-like').forEach(function (btn) {
    btn.addEventListener('click', async function () {
      if (btn.disabled) return;
      btn.disabled = true;
      try {
        const res = await fetch(btn.dataset.url, {
          method: 'POST',
          headers: { 'X-CSRFToken': meta ? meta.content : '', 'Accept': 'application/json' },
        });
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        btn.classList.toggle('is-liked', data.liked);
        btn.setAttribute('aria-pressed', data.liked ? 'true' : 'false');
        btn.querySelector('.com-heart').textContent = data.liked ? '♥' : '♡';
        btn.querySelector('.com-like-count').textContent = data.total;
      } catch (e) {
        console.error(e);
      } finally {
        btn.disabled = false;
      }
    });
  });
})();

// Copiar el enlace público de una publicación
document.querySelectorAll('button.com-share[data-copy]').forEach(function (btn) {
  btn.addEventListener('click', async function () {
    const etiqueta = btn.querySelector('span');
    try {
      await navigator.clipboard.writeText(btn.dataset.copy);
      etiqueta.textContent = '¡Copiado!';
    } catch (e) {
      window.prompt('Copia este enlace:', btn.dataset.copy);
    }
    setTimeout(function () { etiqueta.textContent = 'Copiar enlace'; }, 1800);
  });
});
