/*
 * Datas no formato brasileiro (dd/mm/aaaa).
 *
 * O <input type="date"> do navegador mostra a data no idioma do navegador/Windows
 * (em inglês vira mm/dd/aaaa) e a página não consegue mudar isso. Aqui cada campo
 * de data vira um campo de texto com máscara dd/mm/aaaa, e o campo original fica
 * escondido guardando o valor em ISO (aaaa-mm-dd) — então o servidor e os scripts
 * das páginas continuam lendo/gravando `.value` como sempre.
 */
(function () {
  var getSet = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  var pad = function (n) { return String(n).padStart(2, '0'); };

  function paraBR(iso) {
    var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
    return m ? m[3] + '/' + m[2] + '/' + m[1] : '';
  }

  function paraISO(br) {
    var m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(br);
    if (!m) return null;
    var d = +m[1], mo = +m[2], y = +m[3];
    var dt = new Date(y, mo - 1, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== mo - 1 || dt.getDate() !== d) return null;
    return y + '-' + pad(mo) + '-' + pad(d);
  }

  document.querySelectorAll('input[type="date"]').forEach(function (el) {
    var min = el.getAttribute('min') || '';
    var max = el.getAttribute('max') || '';
    var txt = document.createElement('input');
    txt.type = 'text';
    txt.inputMode = 'numeric';
    txt.maxLength = 10;
    txt.placeholder = 'dd/mm/aaaa';
    txt.autocomplete = 'off';
    txt.className = el.className;
    txt.style.cssText = el.style.cssText;
    txt.required = el.required;
    txt.value = paraBR(getSet.get.call(el));
    el.after(txt);

    el.type = 'hidden';
    el.removeAttribute('required');

    function sincronizar() {
      if (!txt.value) {
        getSet.set.call(el, '');
        txt.setCustomValidity('');
        return;
      }
      var iso = paraISO(txt.value);
      if (!iso || (min && iso < min) || (max && iso > max)) {
        getSet.set.call(el, '');
        txt.setCustomValidity(iso && min && iso < min ? 'Essa data já passou.' : 'Data inválida. Use dd/mm/aaaa.');
        return;
      }
      txt.setCustomValidity('');
      getSet.set.call(el, iso);
      el.dispatchEvent(new Event('input', { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    }

    txt.addEventListener('input', function () {
      var d = txt.value.replace(/\D/g, '').slice(0, 8);
      if (d.length > 4) txt.value = d.slice(0, 2) + '/' + d.slice(2, 4) + '/' + d.slice(4);
      else if (d.length > 2) txt.value = d.slice(0, 2) + '/' + d.slice(2);
      else txt.value = d;
      sincronizar();
    });

    // Scripts da página que fazem `campo.value = 'aaaa-mm-dd'` continuam funcionando.
    Object.defineProperty(el, 'value', {
      configurable: true,
      get: function () { return getSet.get.call(el); },
      set: function (v) {
        getSet.set.call(el, v);
        txt.value = paraBR(v);
        txt.setCustomValidity('');
      }
    });

    // Esconder/mostrar o campo original (classe d-none) vale para o novo também.
    function espelharClasse() { txt.classList.toggle('d-none', el.classList.contains('d-none')); }
    new MutationObserver(espelharClasse).observe(el, { attributes: true, attributeFilter: ['class'] });
    espelharClasse();
  });
})();
