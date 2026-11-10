/*
 * Index page behaviour:
 *   - sorting (click a header)
 *   - per-column filters
 *   - resizable columns (drag the handle on a header's right edge)
 *
 * Expects the markup from templates/index.html:
 *   #records-table (with data-index and a <colgroup> whose <col>
 *   elements carry data-width), .column-filter inputs, .col-resizer
 *   handles, #visible-count, #no-matches, #clear-filters,
 *   #reset-widths.
 */

(function () {

  const table = document.getElementById('records-table');

  if (!table) {
    return;
  }


  const tbody = table.tBodies[0];

  const headers = table.querySelectorAll('th.sortable');

  const filters = table.querySelectorAll('.column-filter');

  const countLabel = document.getElementById('visible-count');

  const noMatches = document.getElementById('no-matches');

  const clearBtn = document.getElementById('clear-filters');

  const resetWidthsBtn = document.getElementById('reset-widths');


  const originalRows = Array.from(tbody.rows);

  const total = originalRows.length;


  let sortCol = null;

  let sortDir = 'asc';


  // -------------------------------------------------------------------
  // Sorting and filtering
  // -------------------------------------------------------------------

  // Retrieve the original value of a cell.

  const cellValue = (row, col) => {

    return (
      row.cells[col].dataset.value || ''
    ).trim();

  };


  // Check whether a value is numeric.

  const isNumeric = (value) => {

    return (
      value !== ''
      && !isNaN(Number(value))
    );

  };


  // Compare two values.

  function compare(a, b) {

    // Keep empty values at the bottom.

    if (a === '' && b === '') {
      return 0;
    }

    if (a === '') {
      return 1;
    }

    if (b === '') {
      return -1;
    }


    let result;


    if (isNumeric(a) && isNumeric(b)) {

      result = Number(a) - Number(b);

    } else {

      result = a.localeCompare(
        b,
        undefined,
        {
          numeric: true,
          sensitivity: 'base'
        }
      );

    }


    return sortDir === 'asc'
      ? result
      : -result;

  }


  // Sort the table.

  function applySort() {

    let rows;


    if (sortCol === null) {

      rows = originalRows.slice();

    } else {

      rows = originalRows.slice().sort((r1, r2) => {

        const a = cellValue(r1, sortCol);

        const b = cellValue(r2, sortCol);

        return compare(a, b);

      });

    }


    rows.forEach((row) => {

      tbody.appendChild(row);

    });


    // Update sorting indicators.

    headers.forEach((th) => {

      const indicator = th.querySelector('.sort-indicator');

      if (Number(th.dataset.col) === sortCol) {

        th.setAttribute(
          'aria-sort',
          sortDir === 'asc'
            ? 'ascending'
            : 'descending'
        );

        indicator.textContent = (
          sortDir === 'asc'
            ? '▲'
            : '▼'
        );

      } else {

        th.setAttribute('aria-sort', 'none');

        indicator.textContent = '';

      }

    });

  }


  // Apply individual column filters.

  function applyFilters() {

    const active = Array.from(filters)

      .map((input) => ({

        col: Number(input.dataset.col),

        term: input.value.trim().toLowerCase()

      }))

      .filter((filter) => filter.term !== '');


    let visible = 0;


    originalRows.forEach((row) => {

      const match = active.every((filter) => {

        return cellValue(
          row,
          filter.col
        ).toLowerCase().includes(filter.term);

      });


      row.classList.toggle(
        'd-none',
        !match
      );


      if (match) {
        visible++;
      }

    });


    if (countLabel) {

      countLabel.textContent = (
        `Showing ${visible} of ${total} rows on this page`
      );

    }


    if (noMatches) {

      noMatches.classList.toggle(
        'd-none',
        visible !== 0
      );

    }

  }


  // Header click: sort.

  headers.forEach((th) => {

    th.addEventListener('click', () => {

      const col = Number(th.dataset.col);


      if (sortCol === col) {

        sortDir = (
          sortDir === 'asc'
            ? 'desc'
            : 'asc'
        );

      } else {

        sortCol = col;

        sortDir = 'asc';

      }


      applySort();

    });

  });


  // Filter input changes.

  filters.forEach((input) => {

    input.addEventListener(
      'input',
      applyFilters
    );

  });


  // Clear all filters and sorting.

  if (clearBtn) {

    clearBtn.addEventListener('click', () => {

      filters.forEach((input) => {

        input.value = '';

      });


      sortCol = null;

      sortDir = 'asc';


      applySort();

      applyFilters();

    });

  }


  // -------------------------------------------------------------------
  // Resizable columns
  // -------------------------------------------------------------------

  const cols = Array.from(table.querySelectorAll('colgroup col'));

  const wrapper = table.parentElement;

  const MIN_WIDTH = 60;

  const STORAGE_KEY = 'columnWidths:' + (table.dataset.index || 'default');

  const defaults = cols.map((col) => Number(col.dataset.width));


  function updateTableWidth() {

    const sum = cols.reduce(
      (acc, col) => acc + parseFloat(col.style.width),
      0
    );

    table.style.width = sum + 'px';

  }


  function setWidth(index, width) {

    cols[index].style.width = (
      Math.max(MIN_WIDTH, Math.round(width)) + 'px'
    );

    updateTableWidth();

  }


  function saveWidths() {

    try {

      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify(
          cols.map((col) => parseFloat(col.style.width))
        )
      );

    } catch (error) {
      // Storage unavailable: widths simply will not persist.
    }

  }


  function loadWidths() {

    try {

      const saved = JSON.parse(
        localStorage.getItem(STORAGE_KEY) || 'null'
      );

      if (
        Array.isArray(saved)
        && saved.length === cols.length
        && saved.every((w) => typeof w === 'number' && w >= MIN_WIDTH)
      ) {

        saved.forEach((w, i) => {
          cols[i].style.width = w + 'px';
        });

        updateTableWidth();

        return true;

      }

    } catch (error) {
      // Ignore corrupt or unavailable storage.
    }

    return false;

  }


  // Default widths, stretched to fill the available space.
  // The last column (Actions) keeps its fixed width.

  function applyDefaultWidths() {

    const last = defaults.length - 1;

    const resizableSum = defaults
      .slice(0, last)
      .reduce((acc, w) => acc + w, 0);

    const available = wrapper.clientWidth - defaults[last];

    const factor = (
      available > resizableSum
        ? available / resizableSum
        : 1
    );

    defaults.forEach((w, i) => {

      cols[i].style.width = (
        Math.round(i === last ? w : w * factor) + 'px'
      );

    });

    updateTableWidth();

  }


  document.querySelectorAll('.col-resizer').forEach((handle) => {

    const index = Number(handle.dataset.col);


    // Never let a click on the handle trigger sorting.

    handle.addEventListener('click', (event) => {

      event.stopPropagation();

    });


    // Double-click: restore this column's default width.

    handle.addEventListener('dblclick', (event) => {

      event.stopPropagation();

      setWidth(index, defaults[index]);

      saveWidths();

    });


    handle.addEventListener('pointerdown', (event) => {

      event.preventDefault();

      event.stopPropagation();


      const startX = event.clientX;

      const startWidth = parseFloat(cols[index].style.width);


      handle.setPointerCapture(event.pointerId);

      handle.classList.add('active');

      document.body.classList.add('col-resizing');


      const onMove = (moveEvent) => {

        setWidth(
          index,
          startWidth + (moveEvent.clientX - startX)
        );

      };


      const onEnd = (endEvent) => {

        handle.releasePointerCapture(endEvent.pointerId);

        handle.classList.remove('active');

        document.body.classList.remove('col-resizing');

        handle.removeEventListener('pointermove', onMove);

        handle.removeEventListener('pointerup', onEnd);

        handle.removeEventListener('pointercancel', onEnd);

        saveWidths();

      };


      handle.addEventListener('pointermove', onMove);

      handle.addEventListener('pointerup', onEnd);

      handle.addEventListener('pointercancel', onEnd);

    });

  });


  if (resetWidthsBtn) {

    resetWidthsBtn.addEventListener('click', () => {

      try {
        localStorage.removeItem(STORAGE_KEY);
      } catch (error) {
        // Ignore.
      }

      applyDefaultWidths();

    });

  }


  // Initial state.

  if (!loadWidths()) {
    applyDefaultWidths();
  }

  applyFilters();

})();