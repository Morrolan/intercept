// Shared original: ami/shared/ui/explain.js. Edit there and run sync-shared.
// Apps own wording, preferences and optional speech. No HTML is interpreted.
(function () {
  'use strict';
  window.Explain = Object.freeze({ mount });
  function mount({ getItem, selector = '[data-explain]', enabled = () => true,
    delay = () => 1000, labels = {}, id = 'explainTip', speak,
    isActionable = anchor => !!anchor.closest('button,a,input,select,label,[role="button"]') }) {
    const tip = document.getElementById(id) || document.createElement('div');
    tip.id = id; tip.className = 'sig-tip'; tip.setAttribute('role', speak ? 'dialog' : 'tooltip');
    if (!tip.isConnected) document.body.append(tip);
    if (speak) tip.classList.add('interactive');
    function describe(anchor, add) {
      const ids = new Set((anchor.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
      if (add) ids.add(id); else ids.delete(id);
      if (ids.size) anchor.setAttribute('aria-describedby', [...ids].join(' '));
      else anchor.removeAttribute('aria-describedby');
    }
    let sigTipAnchor = null;
    let sigTipTimer = null;
    let sigTipClicked = null; // what was just clicked: no tooltip for it until the pointer leaves
    let sigTipClosedAt = 0;   // when the pointer last left a showing tooltip's term
    let touchActed = null;
    let lastPointerType = 'mouse';
    let focusFromPointer = false;

    function sigTipLine(label, text){
      const line = document.createElement('div');
      line.className = 'sig-tip-line';
      const l = document.createElement('span');
      l.className = 'sig-tip-label';
      l.textContent = label;
      const value = document.createElement('span');
      value.textContent = text || '';
      line.append(l, value);
      return line;
    }

    function showSigTip(anchor){
      const item = getItem(anchor);
      if (!enabled() || !item || !tip) return;
      if (sigTipAnchor && sigTipAnchor !== anchor) describe(sigTipAnchor, false);

      const head = document.createElement('div');
      head.className = 'sig-tip-head';
      const term = document.createElement('strong');
      term.textContent = item.term;
      const tag = document.createElement('span');
      tag.className = 'sig-tip-tag';
      tag.textContent = item.category || '';
      if (speak) tip.setAttribute('aria-label', item.term);
      head.append(term, tag);
      const example = document.createElement('div');
      example.className = 'sig-tip-example';
      example.textContent = item.example || '';
      const foot = document.createElement('div');
      foot.className = 'sig-tip-foot';
      foot.textContent = labels.foot || '';
      tip.replaceChildren(head);
      for (const [label, value] of [[labels.meaning || 'Meaning', item.meaning], [labels.matters || 'Why it matters', item.matters], [labels.notMeaning || 'Not proof of', item.notMeaning]]) {
        if (value) tip.append(sigTipLine(label, value));
      }
      if (item.example) tip.append(example);
      if (labels.foot) tip.append(foot);
      if (speak) {
        const read = document.createElement('button');
        read.type = 'button'; read.className = 'sig-tip-read';
        read.textContent = labels.read || 'Read aloud';
        read.addEventListener('click', () => speak([item.term, item.meaning, item.matters, item.notMeaning, item.example].filter(Boolean).join('. ')));
        tip.append(read);
      }

      sigTipAnchor = anchor;
      describe(anchor, true);
      tip.classList.add('show');
      // Phones: dock to the bottom so the tooltip is never clipped
      const docked = window.innerWidth <= 600;
      tip.classList.toggle('docked', docked);
      if (docked) return;
      const r = anchor.getBoundingClientRect();
      const w = tip.offsetWidth, h = tip.offsetHeight, m = 8;
      let top = r.bottom + m;
      if (top + h > window.innerHeight - m) top = Math.max(m, r.top - h - m);
      tip.style.left = `${Math.min(Math.max(m, r.left + r.width / 2 - w / 2), window.innerWidth - w - m)}px`;
      tip.style.top = `${top}px`;
    }

    function hideSigTip(){
      clearTimeout(sigTipTimer);
      tip?.classList.remove('show');
      if (sigTipAnchor) describe(sigTipAnchor, false);
      sigTipAnchor = null;
    }

    document.addEventListener('pointerdown', e => {
      lastPointerType = e.pointerType;
      focusFromPointer = true;
      // A click means acting, not reading: cancel a tooltip on its way (touch has its own tap handling)
      if (e.pointerType === 'touch') return;
      clearTimeout(sigTipTimer);
      sigTipClicked = e.target.closest?.(selector) || null;
      if (sigTipAnchor && !e.target.closest(`#${tip.id}`)) hideSigTip();
    }, true);
    document.addEventListener('keydown', e => { focusFromPointer = false; if (e.key === 'Escape') hideSigTip();
      if (e.key === 'F1' && speak && sigTipAnchor) { e.preventDefault(); tip.querySelector('button')?.focus(); } }, true);

    document.addEventListener('pointerover', e => {
      if (e.pointerType === 'touch') return;
      const anchor = e.target.closest?.(selector);
      if (!anchor || anchor === sigTipAnchor || anchor === sigTipClicked) return;
      clearTimeout(sigTipTimer);
      // Already reading tooltips (one open, or just left): the next one follows quickly
      const reading = sigTipAnchor || Date.now() - sigTipClosedAt < 500;
      sigTipTimer = setTimeout(() => showSigTip(anchor), reading ? 120 : delay());
    });

    document.addEventListener('pointerout', e => {
      if (e.pointerType === 'touch') return;
      const anchor = e.target.closest?.(selector);
      if (!anchor || anchor.contains(e.relatedTarget)) return;
      clearTimeout(sigTipTimer);
      if (sigTipClicked === anchor) sigTipClicked = null;
      if (sigTipAnchor === anchor) {
        if (speak && tip.contains(e.relatedTarget)) return;
        if (speak) sigTipTimer = setTimeout(hideSigTip, 250);
        else hideSigTip();
        sigTipClosedAt = Date.now();
      }
    });

    // Keyboard focus shows the tooltip; pointer focus is handled by hover/tap instead
    document.addEventListener('focusin', e => {
      const anchor = e.target.closest?.(selector);
      if (anchor && !focusFromPointer) showSigTip(anchor);
    });
    document.addEventListener('focusout', e => {
      const anchor = e.target.closest?.(selector);
      if (anchor && sigTipAnchor === anchor && !anchor.contains(e.relatedTarget) && !tip.contains(e.relatedTarget)) hideSigTip();
    });

    // Touch: tap a term to toggle its tooltip, tap anywhere else to close it
    document.addEventListener('click', e => {
      if (lastPointerType !== 'touch') return;
      const anchor = e.target.closest(selector);
      if (anchor && enabled() && getItem(anchor)) {
        if (touchActed === anchor) return;
        // Clickable boxes (market cards, article cards): first tap explains, second tap acts
        const actionable = isActionable(anchor);
        if (sigTipAnchor === anchor) {
          hideSigTip();
          if (actionable) {
            touchActed = anchor;
            setTimeout(() => { touchActed = null; }, 0);
            return;
          }
        }
        else showSigTip(anchor);
        e.preventDefault();
        e.stopPropagation();
      } else if (sigTipAnchor && !e.target.closest(`#${tip.id}`)) {
        hideSigTip();
      }
    }, true);

    window.addEventListener('scroll', () => { if (sigTipAnchor && lastPointerType !== 'touch') hideSigTip(); }, true);
    window.addEventListener('resize', () => hideSigTip());


    tip.addEventListener('pointerenter', () => clearTimeout(sigTipTimer));
    tip.addEventListener('pointerleave', e => { if (speak && !sigTipAnchor?.contains(e.relatedTarget)) hideSigTip(); });
    tip.addEventListener('focusout', e => { if (!tip.contains(e.relatedTarget)) hideSigTip(); });
    return Object.freeze({ show: showSigTip, hide: hideSigTip });
  }
})();
