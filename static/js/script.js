// TAB HANDLING
// Keep the active customer dashboard tab in sync with the content currently loaded into the account area.
function setActiveCustomerTab(page) {
  document.querySelectorAll(".tabs-list .tab-item").forEach(function (button) {
    button.classList.toggle("active", button.dataset.page === page);
  });
}

// GENERIC MODAL SYSTEM
function setupModals() {
  document.addEventListener("click", function (e) {
    const openBtn = e.target.closest("[data-open-modal]");
    const closeBtn = e.target.closest("[data-close-modal]");
    const overlay = e.target.classList.contains("modal-overlay")
      ? e.target
      : null;

    // OPEN MODAL
    if (openBtn) {
      const modal = document.getElementById(openBtn.dataset.openModal);
      if (modal) modal.classList.add("active");
    }

    // CLOSE MODAL
    if (closeBtn) {
      const modal = document.getElementById(closeBtn.dataset.closeModal);
      if (modal) modal.classList.remove("active");
    }

    // CLICK OUTSIDE CLOSE
    if (overlay) {
      overlay.classList.remove("active");
    }
  });
}

// LOAD PARTIAL PAGES
// Load dashboard tab content on demand so the account page can switch sections without a full page refresh.
function loadPage(page, updateHistory = true) {
  const app = document.getElementById("app");
  if (!app) return;

  fetch("/" + page + "?partial=1")
    .then((res) => res.text())
    .then((data) => {
      app.innerHTML = data;
      setActiveCustomerTab(page);
      initPageFeatures();

      if (updateHistory) {
        const url = new URL(window.location.href);
        url.searchParams.set("tab", page);
        window.history.replaceState({}, "", url);
      }
    });
}

// STOCK CONTROLS
// These controls keep the visible stock value and the form input aligned while the producer adjusts quantities.
function setupStockControls() {
  document.querySelectorAll(".stock-row").forEach(function (row) {
    const minusBtn = row.querySelector(".minus-btn");
    const plusBtn = row.querySelector(".plus-btn");
    const input = row.querySelector(".stock-input");
    const currentValue = row.querySelector(".stock-current-value");

    if (!minusBtn || !plusBtn || !input) return;

    function sync() {
      let value = parseInt(input.value, 10);
      if (isNaN(value) || value < 0) value = 0;
      input.value = value;
      if (currentValue) currentValue.textContent = value;
    }

    minusBtn.onclick = () => {
      input.value = Math.max(0, (parseInt(input.value) || 0) - 1);
      sync();
    };

    plusBtn.onclick = () => {
      input.value = (parseInt(input.value) || 0) + 1;
      sync();
    };

    input.oninput = sync;
    sync();
  });
}

// PRODUCT SEARCH (PRODUCER SIDE)
function setupProducerProductSearch() {
  const searchInput = document.getElementById("producerProductsSearch");
  const rows = Array.from(document.querySelectorAll("[data-product-row]"));
  const emptyState = document.getElementById("producerProductsEmptySearch");

  if (!searchInput || rows.length === 0) return;

  function filter() {
    const query = searchInput.value.trim().toLowerCase();
    let visibleCount = 0;

    rows.forEach(function (row) {
      const name = (row.dataset.productName || "").toLowerCase();
      const category = (row.dataset.productCategory || "").toLowerCase();

      if (query === "") {
        row.hidden = false;
        visibleCount++;
        return;
      }

      const matches = name.includes(query) || category.includes(query);

      row.hidden = !matches;

      if (matches) {
        visibleCount++;
      }
    });

    if (emptyState) {
      emptyState.hidden = !(query !== "" && visibleCount === 0);
    }
  }

  searchInput.addEventListener("input", filter);
  filter();
}

// EDIT + DELETE PRODUCT MODALS
function setupProductModals() {
  const editModal = document.getElementById("editProductModal");
  const editForm = document.getElementById("editProductForm");

  const deleteModal = document.getElementById("deleteProductModal");
  const deleteForm = document.getElementById("deleteProductForm");
  const deleteMessage = document.getElementById("deleteProductMessage");

  document.querySelectorAll("[data-edit-product]").forEach((btn) => {
    btn.onclick = function () {
      const row = btn.closest("[data-product-row]");
      if (!row || !editModal) return;

      editForm.action = "/update-product/" + row.dataset.productId;

      document.getElementById("edit_product_name").value =
        row.dataset.productTitle || "";
      document.getElementById("edit_description").value =
        row.dataset.productDescription || "";
      document.getElementById("edit_price").value =
        row.dataset.productPrice || "";
      document.getElementById("edit_stock").value =
        row.dataset.productStock || "";
      document.getElementById("edit_category").value =
        row.dataset.productCategoryTitle || "";

      editModal.classList.add("active");
    };
  });

  document.querySelectorAll("[data-delete-product]").forEach((btn) => {
    btn.onclick = function () {
      const row = btn.closest("[data-product-row]");
      if (!row || !deleteModal) return;

      deleteForm.action = "/delete-product/" + row.dataset.productId;

      if (deleteMessage) {
        deleteMessage.textContent =
          'Are you sure you want to delete "' +
          (row.dataset.productTitle || "this product") +
          '"?';
      }

      deleteModal.classList.add("active");
    };
  });
}

// PRODUCER ORDERS TABS
function setupOrderTabs() {
  const tabs = Array.from(document.querySelectorAll("[data-orders-tab]"));
  const cards = Array.from(document.querySelectorAll("[data-orders-group]"));
  const emptyState = document.getElementById("producerOrdersEmpty");

  if (tabs.length === 0 || cards.length === 0) return;

  function setTab(group) {
    let count = 0;

    tabs.forEach((t) =>
      t.classList.toggle("active", t.dataset.ordersTab === group),
    );

    cards.forEach((card) => {
      const match = card.dataset.ordersGroup === group;
      card.hidden = !match;
      if (match) count++;
    });

    if (emptyState) {
      const p = emptyState.querySelector("p");
      if (p) p.textContent = count === 0 ? "No " + group + " orders" : "";
      emptyState.hidden = count !== 0;
    }
  }

  tabs.forEach((tab) => {
    tab.onclick = () => setTab(tab.dataset.ordersTab);
  });

  setTab("pending");
}

// Account Deletion
function setupAccountDeleteModal() {
  const deleteAccountModal = document.getElementById("deleteAccountModal");

  document.querySelectorAll("[data-delete-account]").forEach((btn) => {
    btn.onclick = function () {
      if (!deleteAccountModal) return;

      deleteAccountModal.classList.add("active");
    };
  });
}

// Product Quantity: Increase and Decrease
function setupProductQuantity() {
  const qtyInput = document.getElementById("quantity");
  const minusBtn = document.getElementById("minusQty");
  const plusBtn = document.getElementById("plusQty");

  if (!qtyInput || !minusBtn || !plusBtn) return;

  function getLimits() {
    const min = Math.max(parseInt(qtyInput.min, 10) || 1, 1);
    const rawMax = parseInt(qtyInput.max, 10);
    const max = !isNaN(rawMax) && rawMax >= min ? rawMax : null;

    return { min, max };
  }

  function normaliseValue(nextValue) {
    const { min, max } = getLimits();
    let value = parseInt(nextValue, 10);

    if (isNaN(value)) {
      value = min;
    }

    if (value < min) {
      value = min;
    }

    if (max !== null && value > max) {
      value = max;
    }

    qtyInput.value = value;
    minusBtn.disabled = value <= min;
    plusBtn.disabled = max !== null && value >= max;
  }

  minusBtn.addEventListener("click", function (event) {
    event.preventDefault();
    normaliseValue((parseInt(qtyInput.value, 10) || 1) - 1);
  });

  plusBtn.addEventListener("click", function (event) {
    event.preventDefault();
    normaliseValue((parseInt(qtyInput.value, 10) || 1) + 1);
  });

  qtyInput.addEventListener("input", function () {
    normaliseValue(qtyInput.value);
  });

  qtyInput.addEventListener("change", function () {
    normaliseValue(qtyInput.value);
  });

  normaliseValue(qtyInput.value);
}

// INITIALISE EVERYTHING
function initPageFeatures() {
  setupStockControls();
  setupProducerProductSearch();
  setupProductModals();
  setupOrderTabs();
  setupAccountDeleteModal();
  setupProductQuantity();
}

// ON LOAD
document.addEventListener("DOMContentLoaded", function () {
  setupModals(); // global modal handler

  const tabsList = document.querySelector(".tabs-list");

  if (tabsList) {
    const defaultTab = tabsList.dataset.defaultTab || "customer-profile";
    loadPage(defaultTab, false);
  }

  initPageFeatures();
});
