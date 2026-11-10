// Native horizontal scrolling also works without JavaScript. No autoplay.
document.querySelectorAll('.cozy-slider').forEach(slider => {
  const track = slider.querySelector('.slider-track');
  const slides = [...track.children];
  const controls = slider.querySelector('.slider-controls');
  const previous = slider.querySelector('.slider-prev');
  const next = slider.querySelector('.slider-next');
  const position = slider.querySelector('.slider-position');
  let current = 0;
  const update = () => {
    current = Math.max(0, Math.min(slides.length - 1, Math.round(track.scrollLeft / track.clientWidth)));
    position.textContent = `${current + 1} / ${slides.length}`;
    previous.disabled = current === 0;
    next.disabled = current === slides.length - 1;
  };
  const go = index => track.scrollTo({left: Math.max(0, Math.min(slides.length - 1, index)) * track.clientWidth,
    behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'});
  previous.addEventListener('click', () => go(current - 1));
  next.addEventListener('click', () => go(current + 1));
  track.addEventListener('scroll', update, {passive: true});
  track.addEventListener('keydown', event => {
    if (event.target !== track) return;
    if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      go(event.key === 'Home' ? 0 : event.key === 'End' ? slides.length - 1 : current + (event.key === 'ArrowRight' ? 1 : -1));
    }
  });
  window.addEventListener('resize', () => { track.scrollLeft = current * track.clientWidth; update(); });
  controls.hidden = slides.length <= 1;
  update();
});
