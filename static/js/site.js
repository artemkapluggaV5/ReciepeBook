const menu = document.querySelector('.menu-toggle');
document.querySelectorAll('img').forEach(image => {
  const fallback = () => {
    if (image.dataset.fallbackUsed) return;
    image.dataset.fallbackUsed = 'true';
    image.src = document.body.dataset.imageFallback;
  };
  image.addEventListener('error', fallback);
  if (image.complete && !image.naturalWidth) fallback();
});
const nav = document.querySelector('#navigation');
if (menu && nav) {
  menu.addEventListener('click', () => {
    const open = menu.getAttribute('aria-expanded') !== 'true';
    menu.setAttribute('aria-expanded', String(open));
    nav.classList.toggle('is-open', open);
  });
  nav.querySelectorAll('a').forEach(link => link.addEventListener('click', () => {
    menu.setAttribute('aria-expanded', 'false'); nav.classList.remove('is-open');
  }));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') {
      menu.setAttribute('aria-expanded', 'false'); nav.classList.remove('is-open'); menu.focus();
    }
  });
}
const form = document.querySelector('#purchase-form');
if (form) {
  form.addEventListener('submit', () => {
    if (!form.checkValidity()) return;
    const button = form.querySelector('button[type="submit"]');
    button.disabled = true; button.textContent = button.dataset.loading;
    form.setAttribute('aria-busy', 'true');
    form.querySelector('.form-status').textContent = 'Пожалуйста, дождитесь перехода к оплате.';
  });
}
window.addEventListener('pageshow', event => {
  if (event.persisted && form) window.location.reload();
});
const error = document.querySelector('#purchase-error');
if (error) { error.focus(); error.scrollIntoView({block: 'center'}); }

// Poll only in the owning browser; a return URL never proves payment.
const pendingPayment = document.querySelector('[data-payment-pending]');
if (pendingPayment) {
  let attempts = 0;
  const poll = async () => {
    attempts += 1;
    try {
      const response = await fetch(window.location.pathname, {
        headers: {'Accept': 'application/json'}, credentials: 'same-origin', cache: 'no-store'
      });
      if (response.ok) {
        const state = await response.json();
        if (state.status !== 'pending') { window.location.reload(); return; }
      }
    } catch (_) { /* Keep the manual refresh button available. */ }
    if (attempts < 100) window.setTimeout(poll, 3000);
    else document.querySelector('#payment-wait').textContent =
      'Подтверждение задерживается. Обновите статус вручную или обратитесь в поддержку с номером заказа. Если деньги списались, повторно платить не нужно.';
  };
  window.setTimeout(poll, 2000);
}
