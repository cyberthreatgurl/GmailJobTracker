/**
 * Company Autocomplete Widget
 *
 * Replaces a plain <select> or <input> with a typeahead search box that
 * queries /api/company_search/?q=... in real-time.
 *
 * Usage:
 *   initCompanyAutocomplete({
 *     inputId:       'my-search-input',   // text input to attach to
 *     hiddenInputId: 'my-hidden-id',      // hidden input that receives the company id
 *     apiUrl:        '/api/company_search/',
 *     onSelect:      function(company) { ... },  // {id, name} or null for "create new"
 *     showCreateNew: true,                // show "+ Create New Company" option
 *     createNewUrl:  '/label_companies/?company=new',  // URL or callback
 *     placeholder:   'Search companies...',
 *     minChars:      1,                   // minimum chars before searching
 *     extraOptions:  [{id: 'none', name: 'None (Clear Company)'}],  // static options at top
 *   });
 */

(function (window) {
  'use strict';

  const DEBOUNCE_MS = 200;
  const DEBUG = true; // Enable console logging for debugging

  /**
   * Initialize a company autocomplete widget on an existing text input.
   */
  function initCompanyAutocomplete(opts) {
    const input = document.getElementById(opts.inputId);
    if (!input) {
      console.warn('[company_autocomplete] Input not found:', opts.inputId);
      return null;
    }
    
    if (DEBUG) console.log('[company_autocomplete] Initializing on input:', opts.inputId);

    const hiddenInput = opts.hiddenInputId
      ? document.getElementById(opts.hiddenInputId)
      : null;

    const apiUrl = opts.apiUrl || '/api/company_search/';
    const minChars = opts.minChars ?? 1;
    const showCreateNew = opts.showCreateNew ?? false;
    const extraOptions = opts.extraOptions || [];
    const onSelect = opts.onSelect || function () {};

    // ── Build dropdown container ──
    const wrapper = document.createElement('div');
    wrapper.className = 'ca-wrapper';

    // Copy relevant styles to the wrapper so layout isn't broken
    const inputStyle = window.getComputedStyle(input);
    const isFull = input.classList.contains('w-full') || input.style.width === '100%';
    const display = inputStyle.display === 'inline' ? 'inline-block' : inputStyle.display;

    // IMPORTANT: Copy min-width to ensure wrapper doesn't collapse excessively in flex containers
    const minW = inputStyle.minWidth === '0px' || inputStyle.minWidth === 'auto' ? '' : inputStyle.minWidth;
    // If min-width is set on input, use it on wrapper
    const wrapperCss = `position:relative;display:${display};` + (minW ? `min-width:${minW};` : '');

    wrapper.style.cssText = wrapperCss;
    
    // If input is full width, force wrapper to be full width
    if (isFull) {
      wrapper.style.width = '100%';
    }
    
    // Copy flex properties if the input was a flex item
    wrapper.style.flexGrow = inputStyle.flexGrow;
    wrapper.style.flexShrink = inputStyle.flexShrink;
    wrapper.style.flexBasis = inputStyle.flexBasis;
    
    // Copy sizing constraints (crucial for flex items)
    wrapper.style.minWidth = inputStyle.minWidth;
    wrapper.style.maxWidth = inputStyle.maxWidth;

    // Copy margins to maintain spacing
    wrapper.style.marginLeft = inputStyle.marginLeft;
    wrapper.style.marginRight = inputStyle.marginRight;
    wrapper.style.marginTop = inputStyle.marginTop;
    wrapper.style.marginBottom = inputStyle.marginBottom;
    
    // Reset margins on input since wrapper handles them now
    // (Actually keeping them on input might double them if we are not careful, 
    // but usually putting input inside wrapper resets context. 
    // Safest is to zero input margins and put them on wrapper)
    input.style.marginTop = '0';
    input.style.marginBottom = '0';
    input.style.marginLeft = '0';
    input.style.marginRight = '0';

    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    
    if (DEBUG) {
      console.log('[company_autocomplete] Wrapper created and inserted');
      console.log('[company_autocomplete] Wrapper style:', wrapper.style.cssText);
      console.log('[company_autocomplete] Wrapper computed:', window.getComputedStyle(wrapper));
    }

    const dropdown = document.createElement('div');

    dropdown.className = 'ca-dropdown';
    // Ensure display:none is set initially, and z-index is high enough.
    // Also use border-box to contain padding/borders.
    dropdown.style.cssText =
      'position:absolute;top:100%;left:0;right:0;z-index:9999;' +
      'background:#fff;border:1px solid #d1d5db;border-top:none;border-radius:0 0 6px 6px;' +
      'max-height:260px;overflow-y:auto;display:none;box-shadow:0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);' +
      'box-sizing:border-box;color:#1f2937;font-family:inherit;text-align:left;line-height:1.5;min-width:200px;';
    wrapper.appendChild(dropdown);

    // ── State ──
    let debounceTimer = null;
    let activeIndex = -1;
    let currentItems = [];   // [{id, name, type}]
    let selectedCompany = null;

    // Pre-populate if the input already has a value (edit scenarios)
    if (opts.initialId && opts.initialName) {
      selectedCompany = { id: opts.initialId, name: opts.initialName };
      input.value = opts.initialName;
      if (hiddenInput) hiddenInput.value = opts.initialId;
    }

    // ── Helpers ──
    function renderDropdown() {
      if (DEBUG) console.log('[company_autocomplete] renderDropdown called, currentItems:', currentItems.length);
      dropdown.innerHTML = '';
      activeIndex = -1;

      if (currentItems.length === 0) {
        // Optional: Show "No results" if query is long enough
        if (input.value.length >= minChars) {
           const row = document.createElement('div');
           row.className = 'ca-item ca-no-results';
           row.style.cssText = 'padding:0.45rem 0.75rem; color:#9ca3af; font-size:0.9rem; font-style:italic;';
           row.textContent = 'No companies found';
           dropdown.appendChild(row);
           
           // Show "Create New" even if no results
           if (showCreateNew) {
               addCreateNewOption();
           }
           dropdown.style.display = 'block';
           if (DEBUG) console.log('[company_autocomplete] Showing empty results with "Create New"');
        } else {
           dropdown.style.display = 'none';
           if (DEBUG) console.log('[company_autocomplete] Query too short, hiding dropdown');
        }
        return;
      }

      currentItems.forEach(function (item, idx) {
        const row = document.createElement('div');
        row.className = 'ca-item p-2 px-3 cursor-pointer text-sm border-b border-gray-100 hover:bg-blue-50';
        row.dataset.index = idx;

        if (item.type === 'create') {
          row.className = 'ca-item p-2 px-3 cursor-pointer text-sm border-b border-gray-100 flex items-center gap-2 hover:bg-blue-50';
          row.style.cssText =
            'padding:0.45rem 0.75rem;cursor:pointer;font-size:0.9rem;color:#1f2937;' +
            'border-bottom:1px solid #f3f4f6;display:flex;align-items:center;gap:0.5rem;';
          row.innerHTML =
            '<span class="text-blue-600 font-semibold" style="color:#2563eb;font-weight:600;">＋</span>' +
            '<span class="text-blue-600" style="color:#2563eb;">Create New Company</span>';
        } else if (item.type === 'extra') {
          row.style.cssText =
            'padding:0.45rem 0.75rem;cursor:pointer;font-size:0.9rem;color:#1f2937;' +
            'border-bottom:1px solid #f3f4f6;';
          row.innerHTML = '<span class="text-gray-500 italic" style="color:#6b7280;font-style:italic;">' +
            escapeHtml(item.name) + '</span>';
        } else {
          row.style.cssText =
            'padding:0.45rem 0.75rem;cursor:pointer;font-size:0.9rem;color:#1f2937;' +
            'border-bottom:1px solid #f3f4f6;white-space:normal;';
          // Highlight matching substring
          let rowHtml = highlightMatch(item.name, input.value);
          // Show UEI / DUNS as a subtitle so the user can confirm the correct entity
          const subtitleParts = [];
          if (item.uei) subtitleParts.push('UEI ' + escapeHtml(item.uei));
          if (item.duns) subtitleParts.push('DUNS ' + escapeHtml(item.duns));
          if (subtitleParts.length) {
            rowHtml += '<br><span style="font-size:0.76rem;color:#9ca3af;">' + subtitleParts.join('·') + '</span>';
          }
          row.innerHTML = rowHtml;
        }

        row.addEventListener('mousedown', function (e) {
          e.preventDefault();   // prevent blur before click fires
          selectItem(idx);
        });
        row.addEventListener('mouseenter', function () {
          setActive(idx);
        });

        dropdown.appendChild(row);
      });

      dropdown.style.display = 'block';
      if (DEBUG) {
        console.log('[company_autocomplete] Dropdown visible, display:', dropdown.style.display);
        console.log('[company_autocomplete] Dropdown position:', dropdown.getBoundingClientRect());
        console.log('[company_autocomplete] Wrapper position:', wrapper.getBoundingClientRect());
      }
    }

    function addCreateNewOption() {
       const idx = currentItems.length; // Next index
       currentItems.push({ id: null, name: 'Create New Company', type: 'create' });
       
       const row = document.createElement('div');
       row.className = 'ca-item p-2 px-3 cursor-pointer text-sm border-b border-gray-100 flex items-center gap-2 hover:bg-blue-50';
       row.dataset.index = idx;
       // Fallback styles
       row.style.cssText =
         'padding:0.45rem 0.75rem;cursor:pointer;font-size:0.9rem;color:#1f2937;' +
          'border-bottom:1px solid #f3f4f6;display:flex;align-items:center;gap:0.5rem;';
       row.innerHTML =
            '<span class="text-blue-600 font-semibold" style="color:#2563eb;font-weight:600;">＋</span>' +
            '<span class="text-blue-600" style="color:#2563eb;">Create New Company</span>';
            
       row.addEventListener('mousedown', function (e) {
          e.preventDefault();
          selectItem(idx);
       });
       row.addEventListener('mouseenter', function () {
          setActive(idx);
       });
       dropdown.appendChild(row);
    }


    function setActive(idx) {
      const items = dropdown.querySelectorAll('.ca-item');
      items.forEach(function (el) {
        el.style.background = '';
        el.classList.remove('bg-blue-50');
      });
      if (idx >= 0 && idx < items.length) {
        // Use Tailwind if present, else fallback
        items[idx].classList.add('bg-blue-50');
        if (!items[idx].classList.contains('bg-blue-50') && window.getComputedStyle(items[idx]).backgroundColor === 'rgba(0, 0, 0, 0)') {
           items[idx].style.background = '#eff6ff';
        } else {
           // Also set inline for robustness if tailwind classes missing in CSS build
           items[idx].style.background = '#eff6ff';
        }
        activeIndex = idx;
      }
    }

    function selectItem(idx) {
      const item = currentItems[idx];
      if (!item) return;

      if (item.type === 'create') {
        if (typeof opts.createNewUrl === 'function') {
          opts.createNewUrl(input.value);
        } else if (opts.createNewUrl) {
          const url = opts.createNewUrl.includes('?')
            ? opts.createNewUrl + '&new_company_name=' + encodeURIComponent(input.value)
            : opts.createNewUrl + '?new_company_name=' + encodeURIComponent(input.value);
          window.location.href = url;
        }
        closeDropdown();
        onSelect(null);
        return;
      }

      selectedCompany = { id: item.id, name: item.name };
      input.value = item.name;
      if (hiddenInput) hiddenInput.value = item.id;
      closeDropdown();
      onSelect(selectedCompany);
    }

    function closeDropdown() {
      dropdown.style.display = 'none';
      currentItems = [];
      activeIndex = -1;
    }

    function escapeHtml(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    function highlightMatch(name, query) {
      return escapeHtml(name);
    }

    function doSearch(query) {
      if (query.length < minChars) {
        closeDropdown();
        return;
      }

      if (DEBUG) console.log('[company_autocomplete] Searching for:', query);

      fetch(apiUrl + '?q=' + encodeURIComponent(query) + '&limit=20')
        .then(function (r) { 
          if (DEBUG) console.log('[company_autocomplete] API response received');
          return r.json(); 
        })
        .then(function (results) {
          if (DEBUG) console.log('[company_autocomplete] Results:', results);
          currentItems = [];

          // Add extra static options that match
          extraOptions.forEach(function (opt) {
            if (
              opt.name.toLowerCase().includes(query.toLowerCase()) ||
              query.length === 0
            ) {
              currentItems.push({ id: opt.id, name: opt.name, type: 'extra' });
            }
          });

          // Add API results
          results.forEach(function (c) {
            currentItems.push({ id: c.id, name: c.name, uei: c.uei || '', duns: c.duns_number || '', type: 'company' });
          });

          // Add "Create New" option if enabled
          if (showCreateNew) {
            currentItems.push({ id: null, name: 'Create New Company', type: 'create' });
          }

          if (DEBUG) console.log('[company_autocomplete] About to render', currentItems.length, 'items');
          renderDropdown();
        })
        .catch(function (err) {
          console.error('[company_autocomplete] search error:', err);
        });
    }

    // ── Event listeners ──
    input.addEventListener('input', function () {
      // Clear selected company when user types
      if (selectedCompany && input.value !== selectedCompany.name) {
        selectedCompany = null;
        if (hiddenInput) hiddenInput.value = '';
      }

      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        doSearch(input.value.trim());
      }, DEBOUNCE_MS);
    });

    input.addEventListener('focus', function () {
      if (input.value.trim().length >= minChars) {
        doSearch(input.value.trim());
      }
    });

    input.addEventListener('blur', function () {
      // Delay to allow mousedown on dropdown item
      setTimeout(closeDropdown, 150);
    });

    input.addEventListener('keydown', function (e) {
      if (dropdown.style.display === 'none') return;

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setActive(Math.min(activeIndex + 1, currentItems.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setActive(Math.max(activeIndex - 1, 0));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (activeIndex >= 0) {
          selectItem(activeIndex);
        }
      } else if (e.key === 'Escape') {
        closeDropdown();
      }
    });

    // Close on outside click
    document.addEventListener('click', function (e) {
      if (!wrapper.contains(e.target)) {
        closeDropdown();
      }
    });

    // ── Public API ──
    return {
      /** Get the currently selected company {id, name} or null. */
      getSelected: function () {
        return selectedCompany;
      },
      /** Programmatically set the selection. */
      setSelected: function (id, name) {
        selectedCompany = id ? { id: id, name: name } : null;
        input.value = name || '';
        if (hiddenInput) hiddenInput.value = id || '';
      },
      /** Clear the selection and input. */
      clear: function () {
        selectedCompany = null;
        input.value = '';
        if (hiddenInput) hiddenInput.value = '';
        closeDropdown();
      },
      /** Get the raw input value (for free-text scenarios). */
      getValue: function () {
        return input.value;
      },
    };
  }

  // Export
  window.initCompanyAutocomplete = initCompanyAutocomplete;

})(window);
