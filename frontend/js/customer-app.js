  // ========== Globals ==========
  const app = document.getElementById("app");

  const searchForm = document.getElementById("search-form");
  const searchInput = document.getElementById("search-plz");
  const searchRadiusSelect = document.getElementById("search-radius");
  const currentLoc = document.getElementById("current-location");

  const cartDrawer = document.getElementById("cart");
  const cartBtn = document.getElementById("btn-cart");
  const cartClose = document.getElementById("cart-close");
  const cartItemsEl = document.getElementById("cart-items");
  const cartTotalEl = document.getElementById("cart-total");
  const cartCountEl = document.getElementById("cart-count");
  const checkoutBtn = document.getElementById("btn-checkout");

  // --- Elements that exist:
const btnLoginCust = document.getElementById("btn-login-customer");
const btnRegisterCust = document.getElementById("btn-register-customer");
const btnLogout = document.getElementById("btn-logout");
const who = document.getElementById("whoami");

// Safe helpers for optional elements (owner buttons are links in HTML, not JS buttons)
const btnLoginRest = document.getElementById("btn-login-restaurant") || null;
const btnRegisterRest = document.getElementById("btn-register-restaurant") || null;

  // modal (customer auth/profile)
  const modal = document.getElementById("modal-auth");
  const tabLogin = document.getElementById("tab-login");
  const tabRegister = document.getElementById("tab-register");
  const tabProfile = document.getElementById("tab-profile");
  const pnlLogin = document.getElementById("panel-login");
  const pnlRegister = document.getElementById("panel-register");
  const pnlProfile = document.getElementById("panel-profile");
  const btnLoginSubmit = document.getElementById("btn-login-submit");
  const btnRegisterSubmit = document.getElementById("btn-register-submit");
  const btnProfileSave = document.getElementById("btn-profile-save");

  // ========== State ==========
  let token = localStorage.getItem("token") || "";
  let subject = localStorage.getItem("subject") || "";
  let ME = null; // customer profile (if logged in as customer)
  let updateRestaurantSticky = null;

  let CART = { order: [], groups: {} };
  let suppressCartPersistence = false;
  // Menu cache to support menu-based filters efficiently per session
  const MENU_CACHE = Object.create(null); // { [rid]: [menuItems] }
  // UI filters persisted in memory (basic)
  const UI_FILTERS = {
    category: null,         // e.g., 'Italian', 'Burgers', 'Pasta', etc.
    halalOnly: false,
    deals: false,
    stampcards: false,
    openNow: false,
    freeDelivery: false,
    minMaxCents: null,      // e.g., 1000, 1500
    sort: 'best',           // 'best' | 'time' | 'min'
  };

  const PAYMENT_METHODS = [
    { value: "visa", label: "Visa" },
    { value: "mastercard", label: "Mastercard" },
    { value: "klarna", label: "Klarna" },
    { value: "apple_pay", label: "Apple Pay" },
    { value: "google_pay", label: "Google Pay" },
    { value: "wallet", label: "Wallet" },
    { value: "voucher", label: "Voucher (full amount)" },
  ];

  let checkoutSheet = null;
  let checkoutRefs = {};
  let checkoutState = {
    method: PAYMENT_METHODS[0].value,
    voucherCode: "",
    preview: null,
    loading: false,
    restaurant: null,
    statusMessage: "",
    statusKind: "info",
  };

  // ========== Helpers ==========
  function h(tag, attrs = {}, ...children) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") el.className = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null) {
        if (typeof v === "boolean") {
          if (v) el.setAttribute(k, "");
        } else {
          el.setAttribute(k, v);
        }
      }
    }
    for (const c of children.flat()) {
      if (c == null) continue;
      if (typeof c === "string" || typeof c === "number") el.appendChild(document.createTextNode(String(c)));
      else el.appendChild(c);
    }
    return el;
  }
  const money = (c) => ((c || 0) / 100).toFixed(2) + " €";
  const toNumber = (value) => {
    if (value == null) return null;
    if (typeof value === "string") {
      const sanitized = value.replace(/[^0-9,.\-]/g, "").replace(",", ".");
      const n = Number(sanitized);
      return Number.isFinite(n) ? n : null;
    }
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  };
  const normalizeInt = (value) => {
    const n = toNumber(value);
    return Number.isFinite(n) ? Math.round(n) : null;
  };
  const normalizeEurosToCents = (value) => {
    const n = toNumber(value);
    return Number.isFinite(n) ? Math.round(n * 100) : null;
  };
  const debounce = (fn, wait = 250) => {
    let t = null;
    return function debounced(...args) {
      const ctx = this;
      if (t) clearTimeout(t);
      t = setTimeout(() => {
        fn.apply(ctx, args);
      }, wait);
    };
  };
  const isValidPlz = (plz) => /^\d{5}$/.test(String(plz || "").trim());
  const getRestaurantRating = (rest) => {
    if (!rest || typeof rest !== "object") return null;
    const extra = rest.extra && typeof rest.extra === "object" ? rest.extra : null;
    const candidates = [
      rest.rating,
      rest.avg_rating,
      rest.average_rating,
      rest.averageRating,
      extra?.rating,
      extra?.avg_rating,
      extra?.average_rating,
      extra?.score,
    ];
    for (const candidate of candidates) {
      const num = Number(candidate);
      if (Number.isFinite(num)) return num;
    }
    return null;
  };
  const orderTotalCents = (order) => {
    if (!order) return 0;
    const totalCents = normalizeInt(order.total_cents);
    if (totalCents != null) return totalCents;
    const totalEuro = normalizeEurosToCents(order.total);
    if (totalEuro != null) return totalEuro;
    const subtotal = normalizeInt(order.subtotal_cents);
    const shipping = normalizeInt(order.shipping_cents);
    const voucher = normalizeInt(order.voucher_amount_cents);
    if (subtotal != null || shipping != null || voucher != null) {
      return (subtotal ?? 0) + (shipping ?? 0) - (voucher ?? 0);
    }
    return 0;
  };
  const orderDisplayTotalCents = (order) => {
    const total = orderTotalCents(order);
    if (total > 0) return total;
    const subtotal = normalizeInt(order?.subtotal_cents);
    const shipping = normalizeInt(order?.shipping_cents);
    if (subtotal != null || shipping != null) {
      return (subtotal ?? 0) + (shipping ?? 0);
    }
    return total;
  };
  const formatDateTime = (value) => {
    if (!value) return "–";
    try {
      const d = new Date(value);
      return Number.isNaN(d.getTime()) ? value : d.toLocaleString();
    } catch {
      return value;
    }
  };
  const toast = (msg, type = "ok") => {
    const t = h("div", { class: "toast", role: "status" }, (type === "err" ? "⚠️ " : "✅ ") + msg);
    document.getElementById("toasts")?.appendChild(t);
    setTimeout(() => t.remove(), 2000);
  };
  let lastFilterToastAt = 0;
  const setActiveTab = (id) => {
    document.querySelectorAll("[data-nav-tab]").forEach(b => b.classList.toggle("is-active", b.id === id));
  };

  const svgIcon = (svg) => `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  const ICONS = {
    vegan: svgIcon(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><circle fill='#4ade80' cx='32' cy='32' r='32'/><text x='50%' y='56%' fill='#fff' font-family='Arial,Helvetica,sans-serif' font-size='16' text-anchor='middle'>VEGAN</text></svg>`),
    halal: svgIcon(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><circle fill='#1d4ed8' cx='32' cy='32' r='32'/><path fill='#fff' d='M20 20h4v12c0 6 4 10 8 10s8-4 8-10V20h4v12c0 8-5 14-12 14s-12-6-12-14V20Zm4 24h16v4H24z'/></svg>`),
    glutenFree: svgIcon(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><circle fill='#fb923c' cx='32' cy='32' r='32'/><path fill='#fff' d='M22 44c6-8 9-12 12-24 5 12 7 16 12 24H22Z'/><path stroke='#fff' stroke-width='4' d='m20 20 24 24'/></svg>`),
    gluten: svgIcon(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><circle fill='#f97316' cx='32' cy='32' r='32'/><path fill='#fff' d='M22 44c6-8 9-12 12-24 5 12 7 16 12 24H22Z'/></svg>`),
    fire: svgIcon(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><path fill='#f97316' d='M32 6s14 12 14 24-9 18-14 22-14-6-14-18S32 6 32 6Z'/><path fill='#fff' opacity='.7' d='M32 18s6 6 6 12-4 10-6 12-6-4-6-10 6-14 6-14Z'/></svg>`),
    fireOff: svgIcon(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><path fill='#94a3b8' d='M32 6s14 12 14 24-9 18-14 22-14-6-14-18S32 6 32 6Z'/></svg>`),
    cart: svgIcon(`<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><path fill='none' stroke='#1d4ed8' stroke-width='4' d='M16 16h6l6 28h20l6-20H26'/><circle cx='28' cy='52' r='4' fill='#1d4ed8'/><circle cx='46' cy='52' r='4' fill='#1d4ed8'/><circle cx='48' cy='16' r='6' fill='#22c55e'/><path stroke='#14532d' stroke-width='3' d='M45 16h6M48 13v6'/></svg>`)
  };

  function decodeJwtPayload(jwt) {
    const part = (jwt || "").split(".")[1] || "";
    if (!part) return null;
    const normalized = part.replace(/-/g, "+").replace(/_/g, "/");
    const padLength = normalized.length % 4;
    const padded = normalized + (padLength ? "=".repeat(4 - padLength) : "");
    try {
      return JSON.parse(atob(padded));
    } catch {
      return null;
    }
  }

  function resetCartMemory() {
    CART = { order: [], groups: {} };
  }

  const getCartGroup = (rid) => {
    if (rid == null) return null;
    return CART.groups[rid] || null;
  };

  const ensureCartGroup = (restaurant) => {
    if (!restaurant || !restaurant.id) return null;
    let group = CART.groups[restaurant.id];
    if (!group) {
      group = {
        restaurant_id: restaurant.id,
        restaurant: {
          id: restaurant.id,
          name: restaurant.name || "",
          min_order_cents: restaurant.min_order_cents ?? null,
          delivery_fee_cents: restaurant.delivery_fee_cents ?? null,
        },
        items: [],
      };
      CART.groups[restaurant.id] = group;
      CART.order.push(restaurant.id);
    } else if (!group.restaurant) {
      group.restaurant = {
        id: restaurant.id,
        name: restaurant.name || "",
        min_order_cents: restaurant.min_order_cents ?? null,
        delivery_fee_cents: restaurant.delivery_fee_cents ?? null,
      };
    }
    return group;
  };

  const getCartGroupsInOrder = () => CART.order
    .map((rid) => CART.groups[rid])
    .filter((group) => group && Array.isArray(group.items) && group.items.length);

  const removeCartGroup = (rid) => {
    if (rid == null) return;
    const ridKey = Number.isFinite(Number(rid)) ? Number(rid) : rid;
    if (CART.groups[ridKey]) {
      delete CART.groups[ridKey];
      CART.order = CART.order.filter((id) => id !== ridKey);
    }
  };

  function saveToken(t) {
    const prevSubject = subject;
    token = t || "";
    if (!token) {
      const key = cartStorageKey(prevSubject);
      if (key) {
        try {
          localStorage.setItem(key, JSON.stringify(cartSnapshotData()));
        } catch {}
      }
      suppressCartPersistence = true;
      resetCartMemory();
      updateCartUI();
      suppressCartPersistence = false;
      localStorage.removeItem("token");
      localStorage.removeItem("subject");
      subject = "";
      return;
    }

    localStorage.setItem("token", token);
    const payload = decodeJwtPayload(token);
    subject = payload?.sub || "";
    if (subject) localStorage.setItem("subject", subject);
    else localStorage.removeItem("subject");

    resetCartMemory();
    restoreCartFromStorage();
    updateCartUI();
  }

  // ========== Auth UI state ==========
  function updateAuthUI() {
    if (!token) {
      if (who) who.textContent = "Not logged in";
      if (btnLogout) btnLogout.style.display = "none";
      if (btnLoginCust) btnLoginCust.style.display = "";
      if (btnRegisterCust) btnRegisterCust.style.display = "";
      // Owner buttons may not exist; guard
      if (btnLoginRest) btnLoginRest.style.display = "";
      if (btnRegisterRest) btnRegisterRest.style.display = "";
      if (tabProfile) tabProfile.classList.add("hidden");
      ME = null;
    } else {
      if (who) who.textContent = "Logged in: " + (subject || "user");
      if (btnLogout) btnLogout.style.display = "";
      if (btnLoginCust) btnLoginCust.style.display = "none";
      if (btnRegisterCust) btnRegisterCust.style.display = "none";
      if (btnLoginRest) btnLoginRest.style.display = "none";
      if (btnRegisterRest) btnRegisterRest.style.display = "none";
      if (tabProfile) {
        if (subject && subject.startsWith("customer:")) tabProfile.classList.remove("hidden");
        else tabProfile.classList.add("hidden");
      }
    }
  }
  
// Owner buttons (only if present in DOM)
if (btnLoginRest)    btnLoginRest.onclick    = () => (window.location.href = "restaurant-dashboard.html#auth?tab=login");
if (btnRegisterRest) btnRegisterRest.onclick = () => (window.location.href = "restaurant-dashboard.html#auth?tab=register");
  // ========== Cart ==========
  function cartCount(rid = null) {
    if (rid != null) {
      const group = getCartGroup(rid);
      if (!group) return 0;
      return group.items.reduce((a, b) => a + (b.quantity || 0), 0);
    }
    return getCartGroupsInOrder().reduce((total, group) => {
      return total + group.items.reduce((a, b) => a + (b.quantity || 0), 0);
    }, 0);
  }
  function cartSubtotal(rid = null) {
    if (rid != null) {
      const group = getCartGroup(rid);
      if (!group) return 0;
      return group.items.reduce((a, b) => a + b.price_cents * b.quantity, 0);
    }
    return getCartGroupsInOrder().reduce((total, group) => {
      return total + group.items.reduce((a, b) => a + b.price_cents * b.quantity, 0);
    }, 0);
  }
  function cartStorageKey(sub = subject) {
    if (!sub || !sub.startsWith("customer:")) return null;
    const id = sub.split(":")[1];
    if (!id) return null;
    return `cart_customer_${id}`;
  }

  function cartSnapshotData() {
    return {
      order: CART.order.slice(),
      groups: getCartGroupsInOrder().map((group) => ({
        restaurant_id: group.restaurant_id,
        restaurant: group.restaurant
          ? {
              id: group.restaurant.id,
              name: group.restaurant.name || "",
              min_order_cents: group.restaurant.min_order_cents ?? null,
              delivery_fee_cents: group.restaurant.delivery_fee_cents ?? null,
            }
          : null,
        items: group.items.map((i) => ({
          menu_item_id: i.menu_item_id,
          name: i.name,
          price_cents: i.price_cents,
          quantity: i.quantity,
        })),
      })),
    };
  }

  function persistCart() {
    const key = cartStorageKey();
    if (!key) return;
    if (!cartCount()) {
      localStorage.removeItem(key);
      return;
    }
    const snapshot = cartSnapshotData();
    try {
      localStorage.setItem(key, JSON.stringify(snapshot));
    } catch {}
  }

  function restoreCartFromStorage() {
    const key = cartStorageKey();
    if (!key) return;
    const raw = localStorage.getItem(key);
    if (!raw) return;
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || !Array.isArray(parsed.groups)) return;
      resetCartMemory();
      const order = Array.isArray(parsed.order) ? parsed.order.slice() : [];
      parsed.groups.forEach((group) => {
        if (!group || group.restaurant_id == null || !Array.isArray(group.items)) return;
        const ridNum = Number(group.restaurant_id);
        const rid = Number.isFinite(ridNum) ? ridNum : group.restaurant_id;
        const items = group.items
          .map((item) => ({
            menu_item_id: item.menu_item_id,
            name: item.name,
            price_cents: item.price_cents,
            quantity: item.quantity,
          }))
          .filter((i) => i.menu_item_id && i.quantity > 0);
        if (!items.length) return;
        CART.groups[rid] = {
          restaurant_id: rid,
          restaurant: group.restaurant || null,
          items,
        };
        CART.order.push(rid);
      });
      if (order.length) {
        CART.order = order
          .map((rid) => {
            const ridNum = Number(rid);
            return Number.isFinite(ridNum) ? ridNum : rid;
          })
          .filter((rid) => CART.groups[rid]);
        const missing = Object.keys(CART.groups)
          .map((rid) => {
            const ridNum = Number(rid);
            return Number.isFinite(ridNum) ? ridNum : rid;
          })
          .filter((rid) => !CART.order.includes(rid));
        CART.order.push(...missing);
      }
    } catch {
      // malformed snapshot; ignore
    }
  }

  function clearCartStorage(sub = subject) {
    const key = cartStorageKey(sub);
    if (key) localStorage.removeItem(key);
  }

  function updateCartUI() {
    if (!cartItemsEl || !cartTotalEl || !cartCountEl) return;
    cartItemsEl.innerHTML = "";
    const groups = getCartGroupsInOrder();
    if (!groups.length) {
      cartItemsEl.appendChild(h("div", {}, "Your cart is empty."));
    } else {
      groups.forEach((group) => {
        const subtotal = cartSubtotal(group.restaurant_id);
        const restaurantName = group.restaurant?.name || `Restaurant ${group.restaurant_id}`;
        const minOrderCents = group.restaurant?.min_order_cents ?? null;
        const meetsMin = minOrderCents == null || minOrderCents <= 0 || subtotal >= minOrderCents;
        const neededCents = !meetsMin && minOrderCents ? Math.max(0, minOrderCents - subtotal) : 0;

        const header = h("div", { class: "cart__group-head" },
          h("div", { class: "cart__group-title" }, restaurantName),
          h("div", { class: "cart__group-total mono" }, money(subtotal))
        );

        const actions = h("div", { class: "cart__group-actions" },
          h("button", {
            type: "button",
            class: "btn btn--ghost btn--sm",
            onclick: () => { removeCartGroup(group.restaurant_id); updateCartUI(); },
          }, "Remove"),
          h("button", {
            type: "button",
            class: "btn btn--primary btn--sm",
            disabled: !meetsMin,
            ...(meetsMin ? {} : { "aria-disabled": "true" }),
            onclick: () => checkout(group.restaurant_id),
          }, "Checkout")
        );
        if (!meetsMin) {
          actions.appendChild(
            h("span", { class: "cart__group-warning" }, `Add ${money(neededCents)} more to reach minimum order.`)
          );
        }

        const list = h("div", { class: "cart__group-items" });
        group.items.forEach((item) => {
          const row = h("div", { class: "cart__row" },
            h("div", {}, item.name),
            h("div", { class: "right row" },
              h("div", { class: "q" },
                h("button", {
                  type: "button",
                  onclick: () => {
                    item.quantity = Math.max(0, item.quantity - 1);
                    if (item.quantity === 0) {
                      group.items = group.items.filter((x) => x.menu_item_id !== item.menu_item_id);
                      if (!group.items.length) removeCartGroup(group.restaurant_id);
                    }
                    updateCartUI();
                  },
                }, "−"),
                h("input", { type: "text", value: String(item.quantity), readOnly: true }),
                h("button", {
                  type: "button",
                  onclick: () => {
                    item.quantity += 1;
                    updateCartUI();
                  },
                }, "+"),
              ),
              h("span", { class: "mono", style: "min-width:80px;text-align:right" }, money(item.price_cents * item.quantity))
            )
          );
          list.appendChild(row);
        });

        const groupEl = h("section", { class: "cart__group" }, header, list, actions);
        cartItemsEl.appendChild(groupEl);
      });
    }
    cartTotalEl.textContent = money(cartSubtotal());
    cartCountEl.textContent = String(cartCount());
    if (typeof updateRestaurantSticky === "function") {
      try { updateRestaurantSticky(); } catch {}
    }
    if (!suppressCartPersistence) persistCart();
  }
  function openCart(open = true) {
    if (!cartDrawer) return;
    cartDrawer.classList.toggle("is-open", open);
    cartBtn?.setAttribute("aria-expanded", open ? "true" : "false");
  }

  // Add item (enforce single-restaurant cart)
  function addToCart(restaurant, mi) {
    const group = ensureCartGroup(restaurant);
    if (!group) return;
    const found = group.items.find((x) => x.menu_item_id === mi.id);
    if (found) found.quantity += 1;
    else group.items.push({ menu_item_id: mi.id, name: mi.name, price_cents: mi.price_cents, quantity: 1 });
    toast(`Added: ${mi.name}`);
    updateCartUI();
  }

  // ========== Views ==========
  async function renderHome() {
    window.currentView = "home";
    updateRestaurantSticky = null;
    setActiveTab("nav-home");
    app.innerHTML = "";
    const statusBar = h("div", { id: "home-status", class: "card", style: "padding:8px 12px;font-size:12px;color:#666; display:none;" }, "");
    app.appendChild(h("div", { class: "card" }, h("h2", {}, "")));
    const rail = h("div", { class: "rail" });
    app.appendChild(rail);

    try {
      const data = await API.restaurants.list({ all: true });
      if (!data?.length) {
        statusBar.textContent = `API ${window.API_BASE} — 0 restaurants`;
        statusBar.style.display = "";
        app.appendChild(h("div", { class: "card mono" }, "No restaurants found."));
        return;
      }
      statusBar.textContent = `API ${window.API_BASE} — ${data.length} restaurants`;
      statusBar.style.display = "none";
      data.forEach((r) => rail.appendChild(restaurantCard(r)));
      const pc = document.getElementById("place-count"); if (pc) pc.textContent = `${data.length} places`;

      // Also show a menu preview on the home page
      const menuPreviewTitle = h("h2", { class: "section-title" }, "From the menu");
      const menuGrid = h("div", { class: "deals" });
      app.appendChild(menuPreviewTitle);
      app.appendChild(menuGrid);

      // Fetch menus for a few restaurants to avoid too many calls
      const sampleRests = data.slice(0, 6);
      let menus = await Promise.all(
        sampleRests.map(async (r) => {
          try { return (await API.restaurants.menu.list(r.id)).map(mi => ({ mi, r })); }
          catch { return []; }
        })
      );
      menus = menus.flat();
      const items = menus
        .filter(x => (x?.mi?.extra?.is_available !== false))
        .slice(0, 12);

      if (!items.length) {
        menuGrid.appendChild(h("div", { class: "card mono" }, "No dishes yet. Check back soon."));
      } else {
        items.forEach(({ mi, r }) => {
          const ex = mi.extra || {};
          const card = h("div", { class: "card clickable", "data-nav-restaurant": String(r.id) },
            h("div", { class: "card-image", style: mi.image_url ? `background-image:url('${mi.image_url}')` : "" }),
            h("div", { class: "card-content" },
              h("div", { class: "card-title" }, mi.name || "Dish"),
              r ? h("div", { class: "help" }, r.name || "") : null,
              h("div", { class: "card-details" },
                ex.is_vegan ? h("span", { class: "chip" }, "Vegan") : null,
                ex.is_vegetarian ? h("span", { class: "chip" }, "Vegetarian") : null,
                Number.isFinite(ex.spicy_level) && ex.spicy_level > 0 ? h("span", { class: "chip" }, `Spicy ${ex.spicy_level}`) : null,
              ),
              h("div", { class: "card-delivery" },
                h("span", {}, money(mi.price_cents)),
                h("button", { class: "btn", onclick: (e) => { e.stopPropagation(); addToCart(r, mi); openCart(true); } }, "Add")
              )
            )
          );
          card.addEventListener("click", () => { location.hash = `#restaurant/${r.id}`; });
          menuGrid.appendChild(card);
        });
      }
    } catch (e) {
      statusBar.textContent = `Error talking to ${window.API_BASE}: ${e?.message || e}`;
      statusBar.style.color = "#b91c1c"; // red-ish
      statusBar.style.display = "";
      app.appendChild(h("div", { class: "card" }, "Load error: " + (e?.message || "")));
    }
  }

  function restaurantCard(rest) {
    const prep = rest.prep_time_min ?? 20;
    const fee = (rest.delivery_fee_cents ?? 0) / 100;
    const rating = getRestaurantRating(rest);
    const ratingNode = rating != null
      ? h("span", { class: "r-card__rating" }, h("i", { class: "fa-solid fa-star" }), ` ${rating.toFixed(1)}`)
      : h("span", { class: "r-card__rating" }, "New");
  
    const renderMiniMenu = (items) => {
      const list = h("div", { class: "r-mini-list" });
      (items || []).forEach((mi) => {
        list.appendChild(
          h("div", { class: "r-mini-item" },
            mi.image_url ? h("img", { class: "r-mini-thumb", src: mi.image_url, alt: mi.name }) : h("div", { class: "r-mini-thumb" }, "🍽️"),
            h("div", {},
              h("div", { class: "r-mini-name" }, mi.name),
              mi.description ? h("div", { class: "r-mini-meta" }, mi.description) : null
            ),
            h("div", { class: "r-mini-price" }, money(mi.price_cents)),
            h("button", {
              class: "btn btn--ghost btn--sm",
              type: "button",
              onclick: (e) => { e.stopPropagation(); addToCart(rest, mi); openCart(true); }
            }, h("i", { class: "fa-solid fa-plus" }), " Add")
          )
        );
      });
      if (!items || !items.length) list.appendChild(h("div", { class: "help" }, "No menu items yet."));
      return list;
    };
  
    const card = h(
      "article",
      {
        class: "r-card clickable",
        role: "button",
        tabindex: "0",
        "data-nav-restaurant": String(rest.id),
        "aria-label": `Open ${rest.name}`,
      },
      h("div", { class: "r-card__thumb" },
        rest.image_url ? h("img", { src: rest.image_url, alt: rest.name }) : h("div", { class: "r-card__placeholder" }, "🍽️")
      ),
      h("div", { class: "r-card__body" },
        h("div", { class: "r-card__title" }, rest.name),
        h("div", { class: "r-card__line" },
          ratingNode,
          h("span", {}, "•"),
          h("span", {}, h("i", { class: "fa-solid fa-clock" }), ` ${prep}–${prep + 10} min`)
        ),
        h("div", { class: "r-card__line" },
          h("span", {}, h("i", { class: "fa-solid fa-truck" }), " ", fee === 0 ? "Free delivery" : `${fee.toFixed(2)} € delivery`)
        ),
        h("div", { class: "r-card__footer" },
          h("span", { class: "r-card__min-order" }, `Min ${money(rest.min_order_cents) || "0.00 €"}`),
          h("div", { class: "row", style: "gap:8px" },
            h("button", {
              class: "btn btn--ghost btn--sm", type: "button",
              onclick: async (e) => {
                e.stopPropagation();
                const expand = card.querySelector(".r-card__expand");
                const isOpen = !expand.hidden;
                if (isOpen) { expand.hidden = true; card.classList.remove("is-expanded"); return; }
                expand.hidden = false; card.classList.add("is-expanded");
                if (!expand._loaded) {
                  expand.innerHTML = '<div class="help">Loading menu…</div>';
                  try {
                    const items = await API.restaurants.menu.list(rest.id);
                    expand.innerHTML = "";
                    expand.appendChild(renderMiniMenu(items));
                    expand.appendChild(
                      h("div", { style: "margin-top:8px" },
                        h("button", {
                          class: "btn btn--sm", type: "button",
                          onclick: (ev) => { ev.stopPropagation(); location.hash = `#restaurant/${rest.id}`; }
                        }, h("i", { class: "fa-solid fa-up-right-from-square" }), " View full menu")
                      )
                    );
                    expand._loaded = true;
                  } catch (err) { expand.innerHTML = `<div class="help" style="color:#c00">${err?.message || "Load failed"}</div>`; }
                }
              }
            }, "Quick peek"),
            h("button", { class: "r-card__action", type: "button", onclick: (e) => { e.stopPropagation(); location.hash = `#restaurant/${rest.id}`; } }, "Open")
          )
        )
      ),
      h("div", { class: "r-card__expand", hidden: true })
    );
  
    if (subject.startsWith("restaurant:") && String(subject.split(":")[1]) === String(rest.id)) {
      card.appendChild(h("span", { class: "r-card__tag" }, "Yours"));
    }
  
    // Whole card navigates
    card.addEventListener("click", () => { location.hash = `#restaurant/${rest.id}`; });
    card.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); location.hash = `#restaurant/${rest.id}`; } });
  
    return card;
  }
  
  
  



  async function renderRestaurantSearch(initPLZ = "", initRadius = null) {
    window.currentView = "restaurants";
    updateRestaurantSticky = null;
    setActiveTab("nav-restaurants");
    app.innerHTML = "";

    const plzInput = h("input", { placeholder: "Enter PLZ", value: initPLZ, inputmode: "numeric", style: "max-width:220px" });
    const radiusSelect = h("select", { style: "max-width:140px" },
      h("option", { value: "1" }, "1 km"),
      h("option", { value: "5" }, "5 km"),
      h("option", { value: "10" }, "10 km"),
      h("option", { value: "20" }, "20 km"),
      h("option", { value: "30" }, "30 km"),
      h("option", { value: "50" }, "50 km")
    );
    const storedRadius = initRadius != null ? String(initRadius) : (localStorage.getItem("last_radius_km") || "5");
    if (["1","5","10","20","30","50"].includes(storedRadius)) {
      radiusSelect.value = storedRadius;
    } else {
      radiusSelect.value = "5";
    }
    const results = h("div", { class: "list", style: "margin-top:12px" });

    const form = h(
      "form",
      {
        class: "card row",
        onsubmit: (e) => {
          e.preventDefault();
          const plz = plzInput.value.trim();
          if (!plz) return;
          doSearch(plz);
        },
      }
    );

    app.appendChild(form);
    app.appendChild(results);
    wireSidebarFilters();
    if (searchInput && searchInput.value !== plzInput.value) {
      searchInput.value = plzInput.value;
    }

    const debouncedPlzSearch = debounce(() => {
      const plz = plzInput.value.trim();
      if (isValidPlz(plz)) {
        doSearch(plz);
      }
    }, 350);

    plzInput.addEventListener("input", () => {
      const val = plzInput.value.trim();
      if (searchInput && searchInput.value !== val) {
        searchInput.value = val;
      }
      debouncedPlzSearch();
    });

    function getFilters() {
      const openNow = !!document.getElementById("flt-open")?.checked;
      const isNew   = !!document.getElementById("flt-new")?.checked;
      const free    = !!document.getElementById("flt-free")?.checked;
      const deals   = !!document.getElementById("flt-deals")?.checked;
      const stamps  = !!document.getElementById("flt-stamps")?.checked;
      const halal   = !!document.getElementById("flt-halal")?.checked;
      const minSel  = (document.querySelector('input[name="minOrder"]:checked')?.value || 'all');
      let minMaxCents = null;
      if (minSel !== "all") {
        const cents = normalizeEurosToCents(minSel);
        if (Number.isFinite(cents)) minMaxCents = cents;
      }
      const minRating = document.getElementById("flt-rating")?.checked ? 4 : null;
      const sortSel = document.querySelector('.search-sort select');
      const sortVal = (sortSel && (sortSel.value || sortSel.options[sortSel.selectedIndex]?.text || '').toLowerCase()) || '';
      let sort = 'best';
      if (sortVal.includes('delivery time') || sortVal.includes('time')) sort = 'time';
      else if (sortVal.includes('minimum')) sort = 'min';

      // Category/tag from the tags bar (active class)
      const activeTag = document.querySelector('.tags span.active');
      const category = activeTag ? (activeTag.textContent || '').trim() : null;

      const radiusKm = Number(radiusSelect.value) || null;
      return { openNow, isNew, free, deals, stamps, halal, minMaxCents, minRating, sort, category, radiusKm };
    }

    async function getMenu(rid) {
      if (MENU_CACHE[rid]) return MENU_CACHE[rid];
      try {
        const items = await API.restaurants.menu.list(rid);
        MENU_CACHE[rid] = items || [];
        return MENU_CACHE[rid];
      } catch { return []; }
    }

    async function filterByMenus(rows, { halal, category }) {
      if (!halal && !category) return rows;
      const out = [];
      for (const r of rows) {
        const menu = await getMenu(r.id);
        let ok = true;
        if (halal) {
          ok = menu.some(mi => (mi.extra && mi.extra.is_halal) === true);
        }
        if (ok && category && category.toLowerCase() !== 'show all') {
          const needle = category.toLowerCase();
          ok = menu.some(mi => {
            const ex = mi.extra || {};
            const cat = (ex.category || '').toLowerCase();
            const tags = Array.isArray(ex.tags) ? ex.tags.map(t => String(t).toLowerCase()) : [];
            return cat.includes(needle) || tags.some(t => t.includes(needle));
          });
        }
        if (ok) out.push(r);
      }
      return out;
    }

    async function doSearch(plz) {
      localStorage.setItem("last_plz", plz);
      if (currentLoc) {
        const radiusLabel = radiusSelect.value ? ` • Radius ${radiusSelect.value} km` : "";
        currentLoc.textContent = `📍 PLZ ${plz}${radiusLabel}`;
      }
      localStorage.setItem("last_radius_km", radiusSelect.value || "5");
      results.innerHTML = "";
      results.appendChild(h("div", { class: "card" }, `Searching ${plz}…`));
      try {
        const F = getFilters();
        const listArgs = {
          plz,
          nearby: true,
          radius_km: F.radiusKm ?? undefined,
        };
        if (F.openNow) listArgs.now = new Date();
        if (F.free) listArgs.free_delivery = true;
        if (F.minMaxCents != null) listArgs.min_order_max = F.minMaxCents;
        if (F.halal) listArgs.halal = true;
        if (F.category && F.category.toLowerCase() !== "show all") {
          listArgs.category = F.category;
          listArgs.tag = F.category;
        }
        const data = await API.restaurants.list(listArgs);

        let rows = Array.isArray(data) ? data : [];
        if (F.free) rows = rows.filter(r => (r.delivery_fee_cents || 0) === 0);
        if (F.minMaxCents != null) rows = rows.filter(r => (r.min_order_cents || 0) <= F.minMaxCents);

        // new: created within last 14 days (approx)
        if (F.isNew) {
          const cutoff = Date.now() - 14 * 24 * 3600 * 1000;
          rows = rows.filter(r => { const d = new Date(r.created_at || 0); return d.getTime() >= cutoff; });
        }
        // deals / stampcards via restaurant.extra flags
        if (F.deals) rows = rows.filter(r => (r.extra && (r.extra.deal || r.extra.deals)) ? true : false);
        if (F.stamps) rows = rows.filter(r => (r.extra && (r.extra.stampcard || r.extra.stamps)) ? true : false);
        if (F.minRating != null) {
          rows = rows.filter(r => {
            const ratingVal = getRestaurantRating(r);
            return ratingVal != null && ratingVal >= F.minRating;
          });
        }

        // dietary / category filters require menu lookup
        rows = await filterByMenus(rows, { halal: F.halal, category: F.category });

        // sorting
        if (F.sort === 'time') rows.sort((a,b) => (a.prep_time_min||0) - (b.prep_time_min||0));
        if (F.sort === 'min')  rows.sort((a,b) => (a.min_order_cents||0) - (b.min_order_cents||0));
        results.innerHTML = "";

        if (!rows.length) {
          results.appendChild(h("div", { class: "card" }, "No restaurants found for this PLZ."));
          return;
        }

        const exactMatches = rows.filter((r) => (r.postal_code || "").trim() === plz.trim());
        const nearbyMatches = rows.filter((r) => (r.postal_code || "").trim() !== plz.trim());

        const pc = document.getElementById("place-count");
        if (pc) pc.textContent = `${rows.length} places`;

        if (exactMatches.length) {
          results.appendChild(h("h3", { class: "section-title" }, `Delivers to ${plz}`));
          results.appendChild(h("p", { class: "muted" }, `${exactMatches.length} restaurant${exactMatches.length === 1 ? "" : "s"} deliver directly to ${plz}.`));
          const exactRail = h("div", { class: "rail" });
          exactMatches.forEach((r) => exactRail.appendChild(restaurantCard(r)));
          results.appendChild(exactRail);
        }

        if (nearbyMatches.length) {
          const label = exactMatches.length ? `Nearby alternatives (within ${radiusSelect.value} km)` : `Nearby restaurants for ${plz}`;
          results.appendChild(h("h3", { class: "section-title" }, label));
          const descText = exactMatches.length
            ? `Further ${nearbyMatches.length} option${nearbyMatches.length === 1 ? "" : "s"} close to ${plz}.`
            : `${nearbyMatches.length} nearby restaurant${nearbyMatches.length === 1 ? "" : "s"} shown.`;
          results.appendChild(h("p", { class: "muted" }, descText));
          const nearRail = h("div", { class: "rail" });
          nearbyMatches.forEach((r) => nearRail.appendChild(restaurantCard(r)));
          results.appendChild(nearRail);
        }
      } catch (e) {
        results.innerHTML = "";
        results.appendChild(h("div", { class: "card" }, "Search error: " + (e?.message || "")));
      }
    }

    radiusSelect.addEventListener("change", () => {
      localStorage.setItem("last_radius_km", radiusSelect.value || "5");
      if (searchRadiusSelect) searchRadiusSelect.value = radiusSelect.value;
      const p = (plzInput.value || localStorage.getItem("last_plz") || "").trim();
      if (isValidPlz(p)) doSearch(p);
    });

    if (initPLZ) {
      doSearch(initPLZ);
    } else if (plzInput.value.trim()) {
      doSearch(plzInput.value.trim());
    }
    // tags row under search-sort
    document.querySelectorAll('.tags span').forEach(tag => {
      tag.addEventListener('click', () => {
        document.querySelectorAll('.tags span').forEach(t => t.classList.remove('active'));
        tag.classList.add('active');
        const p = (plzInput.value || localStorage.getItem('last_plz') || '').trim();
        if (p) doSearch(p);
      });
    });
  }

  async function renderRestaurant(rid) {
    window.currentView = "restaurant";
    updateRestaurantSticky = null;
    setActiveTab("nav-restaurants");
    app.innerHTML = "";

    let restaurant, menu;
    try {
      const data = await API.restaurants.detail(rid);
      if (data && data.restaurant) {
        restaurant = data.restaurant;
        menu = data.menu || [];
      } else {
        restaurant = data;
        menu = await API.restaurants.menu.list(rid);
      }
    } catch (e) {
      app.appendChild(h("div", { class: "card" }, "Load error: " + (e?.message || "")));
      return;
    }

    const prep = restaurant.prep_time_min ?? 20;
    const fee = (restaurant.delivery_fee_cents ?? 0) / 100;
    const heroBadge = restaurant.is_online ? "Open now" : "Offline";
    const heroChips = [];
    if (restaurant.extra?.deal) heroChips.push("Special deal");
    if (restaurant.extra?.stampcard) heroChips.push("Stampcard");
    if (restaurant.busy_until) {
      const busyDate = new Date(restaurant.busy_until);
      if (!Number.isNaN(busyDate.getTime())) {
        heroChips.push(`Busy until ${busyDate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`);
      }
    }

    const hero = h("section", { class: "restaurant-hero" },
      h("div", { class: "restaurant-hero__media" },
        restaurant.image_url
          ? h("img", { class: "restaurant-hero__img", src: restaurant.image_url, alt: restaurant.name })
          : h("div", { class: "restaurant-hero__img", style: "display:grid;place-items:center;background:#f8fafc;font-size:40px;color:#475569" }, "🍽️"),
        h("span", { class: "restaurant-hero__badge" }, heroBadge)
      ),
      h("div", { class: "restaurant-hero__info" },
        h("h1", { class: "restaurant-hero__title" }, restaurant.name),
        h("div", { class: "restaurant-hero__meta" },
          h("span", {}, h("i", { class: "fa-solid fa-clock" }), ` ${prep}–${prep + 10} min prep`),
          h("span", {}, "•"),
          h("span", {}, h("i", { class: "fa-solid fa-truck" }), ` ${fee === 0 ? "Free delivery" : fee.toFixed(2) + " € delivery"}`),
          restaurant.min_order_cents ? h("span", {}, "•", " Min ", money(restaurant.min_order_cents)) : null
        ),
        restaurant.description ? h("p", { class: "restaurant-hero__desc" }, restaurant.description) : null,
        h("div", { class: "restaurant-hero__meta" },
          h("span", {}, h("i", { class: "fa-solid fa-map-pin" }), ` ${restaurant.street || ""}, ${restaurant.postal_code || ""}`)
        ),
        heroChips.length
          ? h("div", { class: "restaurant-hero__chips" },
              ...heroChips.map((chip) => h("span", { class: "restaurant-hero__chip" }, chip)))
          : null
      )
    );
    app.appendChild(hero);

    if (!menu?.length) {
      app.appendChild(h("div", { class: "card mono" }, "Menu coming soon."));
    } else {
      const slugify = (val) => (val || "menu").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "menu";
      const groups = new Map();
      menu.forEach((mi) => {
        const cat = ((mi.extra && mi.extra.category) || "Chef's picks").trim() || "Chef's picks";
        if (!groups.has(cat)) groups.set(cat, []);
        groups.get(cat).push(mi);
      });

      const navButtons = [];
      const sectionRefs = [];

      if (groups.size > 0) {
        const menuNav = h("div", { class: "restaurant-menu-nav" });
        const sectionsWrap = h("div", {});

        Array.from(groups.entries()).forEach(([category, items], idx) => {
          const sectionId = `menu-${slugify(category)}-${idx}`;

          const btn = h("button", {
            class: "restaurant-menu-nav__btn" + (idx === 0 ? " is-active" : ""),
            type: "button",
            onclick: () => {
              const target = document.getElementById(sectionId);
              if (target) {
                target.scrollIntoView({ behavior: "smooth", block: "start" });
                navButtons.forEach((b) => b.classList.toggle("is-active", b === btn));
              }
            },
          }, category, h("span", { class: "menu-section__count" }, ` (${items.length})`));
          navButtons.push(btn);
          menuNav.appendChild(btn);

          const grid = h("div", { class: "menu-grid" });
          items.forEach((mi) => {
            const ex = mi.extra || {};
            const tagsRaw = Array.isArray(ex.tags) ? ex.tags.map((t) => String(t).trim()).filter(Boolean) : [];
            const tagsLower = tagsRaw.map((t) => t.toLowerCase());
            const isGlutenFree = ex.is_gluten_free === true || tagsLower.some((t) => t.includes("gluten free"));
            const displayTags = tagsRaw.filter((t) => !/gluten\s*free/i.test(t));

            const ingredientsList = Array.isArray(ex.ingredients) ? ex.ingredients.map((t) => String(t).trim()).filter(Boolean) : [];
            const allergenList = Array.isArray(ex.allergens) ? ex.allergens.map((t) => String(t).trim()).filter(Boolean) : [];

            const metaPieces = [];
            if (ex.portion) metaPieces.push(`Portion: ${ex.portion}`);
            if (ex.calories) metaPieces.push(`${ex.calories} kcal`);

            const available = ex.is_available !== false;

            const spiceLevelRaw = Number(ex.spicy_level);
            const spiceLevel = Number.isFinite(spiceLevelRaw) ? Math.max(0, Math.min(3, Math.round(spiceLevelRaw))) : 0;
            const makeFireIcon = (mild = false) => h("i", { class: "fa-solid fa-fire" + (mild ? " menu-card__spice-icon--mild" : "") });
            const spiceIcons = spiceLevel ? Array.from({ length: spiceLevel }, () => makeFireIcon()) : [makeFireIcon(true)];
            const spiceBadge = h("div", { class: "menu-card__spice-badge" + (spiceLevel ? "" : " is-mild") }, ...spiceIcons);

            const priceBadge = h("span", { class: "menu-card__price-badge" }, money(mi.price_cents));

            const imageUrls = [];
            if (mi.image_url) imageUrls.push(mi.image_url);
            if (Array.isArray(ex.images)) {
              ex.images.forEach((url) => {
                if (url && typeof url === "string") imageUrls.push(url.trim());
              });
            }
            const uniqueImages = [...new Set(imageUrls.filter(Boolean))];
            if (!uniqueImages.length) uniqueImages.push("");

            let currentImage = 0;
            const mediaImg = uniqueImages[0]
              ? h("img", { src: uniqueImages[0], alt: mi.name })
              : null;
            const mediaContent = mediaImg || h("div", { class: "menu-card__media-placeholder" }, "🍽️");
            const updateImage = (delta) => {
              if (!mediaImg || uniqueImages.length < 2) return;
              currentImage = (currentImage + delta + uniqueImages.length) % uniqueImages.length;
              mediaImg.src = uniqueImages[currentImage];
            };

            const dietBadges = [];
            if (ex.is_vegan) {
              dietBadges.push(h("span", { class: "menu-card__diet-badge menu-card__diet-badge--vegan" }, h("i", { class: "fa-solid fa-seedling" }), " Vegan"));
            } else if (ex.is_halal) {
              dietBadges.push(h("span", { class: "menu-card__diet-badge menu-card__diet-badge--halal" }, h("i", { class: "fa-solid fa-mosque" }), " Halal"));
            }
            dietBadges.push(
              h("span", { class: "menu-card__diet-badge " + (isGlutenFree ? "menu-card__diet-badge--gluten-free" : "menu-card__diet-badge--gluten") },
                h("i", { class: isGlutenFree ? "fa-solid fa-wheat-awn-slash" : "fa-solid fa-wheat-awn" }),
                isGlutenFree ? " Gluten free" : " Contains gluten"
              )
            );
            const dietOverlay = h("div", { class: "menu-card__diet-badges" }, ...dietBadges);

            const availabilityHint = h(
              "span",
              { class: "menu-card__hint" },
              available ? "Ready to add to your order" : "Currently unavailable"
            );
            const actions = h("div", { class: "menu-card__actions" },
              availabilityHint,
              h("button", {
                class: "menu-card__btn",
                type: "button",
                disabled: !available,
                onclick: (e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  if (available) {
                    addToCart(restaurant, mi);
                    openCart(true);
                  }
                }
              }, h("i", { class: available ? "fa-solid fa-plus" : "fa-solid fa-ban" }), available ? "Add to cart" : "Unavailable")
            );

            const header = h("div", { class: "menu-card__header" },
              h("div", { class: "menu-card__title-group" },
                h("h3", { class: "menu-card__title" }, mi.name)
              )
            );

            const body = h("div", { class: "menu-card__body" },
              header,
              actions
            );

            const makeRow = (label, content) => h(
              "div",
              { class: "menu-card__details-row" },
              h("span", { class: "menu-card__details-label" }, label),
              typeof content === "string"
                ? h("p", { class: "menu-card__details-text" }, content)
                : content
            );

            const detailRows = [];
            if (mi.description) detailRows.push(makeRow("Description", mi.description));
            if (displayTags.length) {
              detailRows.push(makeRow("Tags", h("div", { class: "menu-card__details-tags" }, ...displayTags.map((tag) => h("span", { class: "menu-card__chip" }, tag)))));
            }
            if (metaPieces.length) detailRows.push(makeRow("Info", metaPieces.join(" • ")));
            if (ingredientsList.length) {
              detailRows.push(makeRow("Ingredients", h("div", { class: "menu-card__details-tags" }, ...ingredientsList.map((item) => h("span", { class: "menu-card__chip" }, item)))));
            }
            if (allergenList.length) {
              detailRows.push(makeRow("Allergens", h("div", { class: "menu-card__details-tags" }, ...allergenList.map((item) => h("span", { class: "menu-card__chip" }, item)))));
            }

            if (detailRows.length) {
              const detailsId = `menu_details_${mi.id}`;
              const detailsContainer = h("div", { class: "menu-card__details", id: detailsId }, ...detailRows);
              const toggleBtn = h("button", { class: "menu-card__details-btn", type: "button", "aria-controls": detailsId, "aria-expanded": "false" }, "Show details");
              toggleBtn.addEventListener("click", () => {
                const open = detailsContainer.classList.toggle("is-open");
                toggleBtn.textContent = open ? "Hide details" : "Show details";
                toggleBtn.setAttribute("aria-expanded", open ? "true" : "false");
              });
              const detailsWrapper = h("div", { class: "menu-card__details-wrapper" }, toggleBtn, detailsContainer);
              body.appendChild(detailsWrapper);
            }

            const media = h("div", { class: "menu-card__media" }, mediaContent);
            const mediaBadges = h("div", { class: "menu-card__media-badges" }, priceBadge);
            media.appendChild(mediaBadges);
            if (dietOverlay) media.appendChild(dietOverlay);
            if (mediaImg && uniqueImages.length > 1) {
              media.appendChild(
                h("button", {
                  class: "menu-card__media-nav menu-card__media-nav--prev",
                  type: "button",
                  onclick: (e) => { e.preventDefault(); e.stopPropagation(); updateImage(-1); }
                }, h("i", { class: "fa-solid fa-chevron-left" }))
              );
              media.appendChild(
                h("button", {
                  class: "menu-card__media-nav menu-card__media-nav--next",
                  type: "button",
                  onclick: (e) => { e.preventDefault(); e.stopPropagation(); updateImage(1); }
                }, h("i", { class: "fa-solid fa-chevron-right" }))
              );
            }

            const card = h("article", { class: "menu-card" + (available ? "" : " menu-card--unavailable") },
              body,
              media
            );
            card.appendChild(spiceBadge);

            if (!available) {
              card.appendChild(h("span", { class: "menu-card__badge" }, "Sold out"));
            }
            grid.appendChild(card);
          });

          const section = h("section", { class: "menu-section", id: sectionId },
            h("div", { class: "menu-section__header" },
              h("h2", { class: "menu-section__title" }, category),
              h("span", { class: "menu-section__count" }, `${items.length} ${items.length === 1 ? "item" : "items"}`)
            ),
            grid
          );
          sectionRefs.push({ el: section, btn });
          sectionsWrap.appendChild(section);
        });

        app.appendChild(menuNav);
        app.appendChild(sectionsWrap);

        if ("IntersectionObserver" in window) {
          const observer = new IntersectionObserver((entries) => {
            const entry = entries
              .filter((e) => e.isIntersecting)
              .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
            if (entry) {
              const ref = sectionRefs.find((r) => r.el === entry.target);
              if (ref) {
                navButtons.forEach((btn) => btn.classList.toggle("is-active", btn === ref.btn));
              }
            }
          }, { rootMargin: "-45% 0px -45% 0px", threshold: [0.2, 0.4, 0.6] });
          sectionRefs.forEach((ref) => observer.observe(ref.el));
        }
      }
    }

    const cartBar = h("div", { class: "restaurant-cart-bar", hidden: true },
      h("span", { class: "restaurant-cart-bar__label" }, ""),
      h("button", { class: "restaurant-cart-bar__cta", type: "button", "data-action": "view" }, "View cart"),
      h("button", { class: "restaurant-cart-bar__cta restaurant-cart-bar__checkout", type: "button", "data-action": "checkout" }, "Checkout")
    );
    const cartBarLabel = cartBar.querySelector(".restaurant-cart-bar__label");
    const cartBarCheckout = cartBar.querySelector('[data-action="checkout"]');
    cartBar.querySelector('[data-action="view"]').addEventListener("click", () => openCart(true));
    cartBarCheckout.addEventListener("click", () => { if (!cartBarCheckout.disabled) checkout(restaurant.id); });
    app.appendChild(cartBar);

    updateRestaurantSticky = () => {
      if (!cartBar.isConnected) return;
      const group = getCartGroup(restaurant.id);
      const hasOther = getCartGroupsInOrder().some((g) => g.restaurant_id !== restaurant.id);
      if (group && group.items.length) {
        cartBar.hidden = false;
        const count = cartCount(restaurant.id);
        const subtotal = cartSubtotal(restaurant.id);
        cartBarLabel.textContent = `${count} ${count === 1 ? "item" : "items"} • ${money(subtotal)}`;
        const minOrder = group.restaurant?.min_order_cents ?? null;
        const meetsMin = minOrder == null || minOrder <= 0 || subtotal >= minOrder;
        cartBarCheckout.disabled = !meetsMin;
        if (!meetsMin) {
          cartBarCheckout.setAttribute("aria-disabled", "true");
          cartBarLabel.textContent += ` (min ${money(minOrder)})`;
        } else {
          cartBarCheckout.removeAttribute("aria-disabled");
        }
      } else if (hasOther) {
        cartBar.hidden = false;
        cartBarLabel.textContent = "Cart currently has items from other restaurants.";
        cartBarCheckout.disabled = true;
        cartBarCheckout.setAttribute("aria-disabled", "true");
      } else {
        cartBar.hidden = true;
        cartBarCheckout.disabled = false;
        cartBarCheckout.removeAttribute("aria-disabled");
      }
    };
    updateRestaurantSticky();
  }

  async function renderOrders() {
    window.currentView = "orders";
    updateRestaurantSticky = null;
    setActiveTab("nav-orders");
    if (!token) return toast("Login first", "err");
    app.innerHTML = "";
    const isCustomer = subject?.startsWith("customer:");
    const isRestaurant = subject?.startsWith("restaurant:");
    const heading = isCustomer ? "My Orders" : (isRestaurant ? "Restaurant Orders" : "Orders");
    const introCard = h("div", { class: "card" }, h("h2", {}, heading));
    if (isRestaurant) {
      introCard.appendChild(
        h("p", { class: "help" }, "These are orders for your logged-in restaurant account.")
      );
    }
    app.appendChild(introCard);

    try {
      const data = await API.orders.mine();
      if (!data?.length) {
        app.appendChild(h("div", { class: "card" }, "No orders yet."));
        return;
      }
      const list = h("div", { class: "order-history" });
      data.forEach((order) => list.appendChild(buildOrderCard(order)));
      app.appendChild(list);
    } catch (e) {
      app.appendChild(h("div", { class: "card" }, "Load error: " + (e?.message || "")));
    }
  }

  async function renderOrderDetail(oid) {
    if (!token) return toast("Login first", "err");
    updateRestaurantSticky = null;
    app.innerHTML = "";
    try {
      const data = await API.orders.detail(oid);
      const { order, items, customer } = data;
      const publicId = order.public_id || `#${order.id}`;
      const restaurantLabel = order.restaurant_public_id || order.restaurant_id;
      const card = h("div", { class: "card" },
        h("h2", {}, `Order ${publicId} — ${order.status}`),
        h("p", {}, `Restaurant: ${restaurantLabel}`),
        h("p", {}, `Created: ${order.created_at}`),
        h("p", {}, `Confirmed: ${order.confirmed_at || "-"}`),
        h("p", {}, `Closed: ${order.closed_at || "-"}`),
        h("p", {}, `Subtotal: ${money(order.subtotal_cents)} • Fee: ${money(order.fee_platform_cents)} • Total: ${money(order.total_cents)}`),
        h("h3", {}, "Items")
      );
      const list = h("div", { class: "list" });
      (items || []).forEach((it) =>
        list.appendChild(
          h("div", { class: "row" },
            h("span", {}, `${it.name_snapshot} × ${it.quantity}`),
            h("span", { class: "right mono" }, money(it.price_cents_snapshot * it.quantity))
          )
        )
      );
      card.appendChild(list);
      if (customer) {
        card.appendChild(h("h3", {}, "Customer"));
        card.appendChild(h("p", {}, `${customer.first_name || ""} ${customer.last_name || ""} — ${customer.postal_code || ""}`));
        if (customer.street) card.appendChild(h("p", {}, customer.street));
      }
      card.appendChild(h("div", {}, h("button", { class: "btn", onclick: () => renderOrders() }, "Back")));
      app.appendChild(card);
    } catch (e) {
      app.appendChild(h("div", { class: "card" }, "Load error: " + (e?.message || "")));
    }
  }

  function buildOrderCard(order) {
    const statusBadge = h("span", { class: "order-card__badge order-card__badge--status" }, order.status);
    const paymentBadge = h("span", {
      class: "order-card__badge order-card__badge--paid",
    }, `Payment: ${order.payment_status}`);

    const publicId = order.public_id || `#${order.id}`;
    const restaurantLabel = order.restaurant_public_id || order.restaurant_id;
    const header = h("div", { class: "order-card__header" },
      h("div", { class: "order-card__title" }, `Order ${publicId}`),
      h("div", { class: "order-card__meta" },
        h("span", {}, `Placed: ${formatDateTime(order.created_at)}`),
        h("span", {}, `Restaurant: ${restaurantLabel}`),
        h("span", {}, `Total: ${money(orderDisplayTotalCents(order))}`),
      ),
      h("div", { class: "order-card__meta" }, statusBadge, paymentBadge),
    );

    const details = h("div", { class: "order-card__details", hidden: true },
      h("p", { class: "checkout-summary__info" }, "Loading…")
    );

    const toggle = h("button", { class: "order-card__toggle", type: "button" }, "Show details");
    toggle.addEventListener("click", async () => {
      const isHidden = details.hidden;
      if (isHidden && !details._loaded) {
        try {
          const detail = await API.orders.detail(order.id);
          details.innerHTML = "";
          const items = h("div", { class: "order-card__items" });
          detail.items.forEach((item) => {
            items.appendChild(
              h("div", { class: "order-card__item" },
                h("span", {}, `${item.quantity} × ${item.name_snapshot}`),
                h("span", { class: "mono" }, money(item.price_cents_snapshot * item.quantity))
              )
            );
          });
          details.appendChild(items);
          const summary = h("div", { class: "order-card__summary" },
            `Subtotal ${money(order.subtotal_cents)} · Delivery ${money(order.shipping_cents)} · Voucher ${money(order.voucher_amount_cents)} · Total ${money(orderTotalCents(order))}`
          );
          if (order.note_for_kitchen) {
            details.appendChild(h("div", { class: "order-card__summary" }, `Note: ${order.note_for_kitchen}`));
          }
          if (detail.customer) {
            details.appendChild(
              h("div", { class: "order-card__summary" },
                `Delivered to ${detail.customer.first_name} ${detail.customer.last_name}${detail.address ? ", " + detail.address.street : ""}`
              )
            );
          }
          details.appendChild(summary);
          details._loaded = true;
        } catch (err) {
          details.innerHTML = "";
          details.appendChild(h("p", { class: "checkout-summary__error" }, err.message || "Failed to load details"));
        }
      }
      details.hidden = !isHidden;
      toggle.textContent = details.hidden ? "Show details" : "Hide details";
    });

    const actions = h("div", { class: "order-card__actions" }, toggle,
      h("button", {
        class: "order-card__toggle",
        type: "button",
        onclick: () => renderOrderDetail(order.id),
      }, "Open full view")
    );

    return h("article", { class: "order-card" }, header, actions, details);
  }

  async function renderWallet() {
    window.currentView = "wallet";
    updateRestaurantSticky = null;
    setActiveTab("nav-wallet");
    if (!token) return toast("Login first", "err");
    app.innerHTML = "";
    try {
      const me = await API.wallet.me();
      const txs = await API.wallet.txns(20);
      const wrap = h("div", { class: "card" },
        h("h2", {}, "Wallet"),
        h("p", {}, "Balance: " + money(me.balance_cents)),
        h("div", { class: "row" },
          h("input", { id: "topup_amt", type: "number", placeholder: "Dev top-up (cents) e.g. 20000" }),
          h("button", {
            class: "btn", onclick: async () => {
              const amt = parseInt(document.getElementById("topup_amt").value, 10);
              if (!amt) return toast("Enter amount in cents", "err");
              try {
                const r = await API.wallet.topup(amt);
                toast("Top-up ok");
                renderWallet();
              } catch (e) { toast(e.message || "Topup failed", "err"); }
            }
          }, "Dev Top-up"),
        ),
        h("h3", {}, "Recent transactions"),
      );
      const list = h("div", { class: "list" });
      txs.forEach(t =>
        list.appendChild(
          h("div", { class: "row" },
            h("span", { class: "mono" }, t.created_at),
            h("span", {}, t.reason || ""),
            h("span", { class: "right mono" }, money(t.amount_cents))
          )
        )
      );
      wrap.appendChild(list);
      app.appendChild(wrap);
    } catch (e) {
      app.appendChild(h("div", { class: "card" }, "Load error: " + (e?.message || "")));
    }
  }

  function resetCheckoutState() {
    checkoutRefs = {};
    checkoutState = {
      method: PAYMENT_METHODS[0].value,
      voucherCode: "",
      preview: null,
      loading: false,
      restaurantId: null,
      restaurant: null,
      statusMessage: "",
      statusKind: "info",
    };
  }

  function closeCheckoutSheet() {
    if (!checkoutSheet) return;
    checkoutSheet.remove();
    checkoutSheet = null;
    document.body.style.removeProperty("overflow");
    resetCheckoutState();
  }

  function renderCheckoutSummary(message) {
    const summary = checkoutRefs.summary;
    if (!summary) return;
    summary.innerHTML = "";

    if (checkoutState.loading) {
      summary.appendChild(h("p", { class: "checkout-summary__info" }, "Calculating total…"));
      return;
    }

    if (message) {
      summary.appendChild(h("p", { class: "checkout-summary__error" }, message));
      return;
    }

    if (!checkoutState.preview) {
      summary.appendChild(h("p", { class: "checkout-summary__info" }, "Enter your address and contact details to preview the total."));
      return;
    }

    const { breakdown } = checkoutState.preview;
    const rows = [
      ["Items subtotal", money(breakdown.subtotal_cents)],
      ["Delivery", money(breakdown.shipping_cents)],
    ];
    if (breakdown.voucher_amount_cents > 0) {
      rows.push(["Voucher", "-" + money(breakdown.voucher_amount_cents)]);
    }
    if (breakdown.wallet_charge_cents > 0) {
      rows.push(["Wallet charge", "-" + money(breakdown.wallet_charge_cents)]);
    }
    rows.push(["Total due", money(breakdown.payment_due_cents)]);

    const list = h("div", { class: "checkout-summary__list" });
    rows.forEach(([label, value], idx) => {
      const row = h("div", { class: "checkout-summary__row" + (idx === rows.length - 1 ? " checkout-summary__row--total" : "") },
        h("span", {}, label),
        h("span", { class: "mono" }, value)
      );
      list.appendChild(row);
    });
    summary.appendChild(list);

    if (checkoutState.method === "voucher" && breakdown.payment_due_cents > 0) {
      summary.appendChild(
        h("p", { class: "checkout-summary__error" }, "Voucher payment requires a voucher that covers the full total.")
      );
    } else if (checkoutState.method === "wallet" && breakdown.wallet_charge_cents <= 0) {
      summary.appendChild(
        h("p", { class: "checkout-summary__error" }, "Wallet payment requires sufficient balance.")
      );
    } else if (breakdown.payment_due_cents === 0) {
      summary.appendChild(
        h("p", { class: "checkout-summary__info" }, "No remaining amount due. You're good to go!")
      );
    }

    if (checkoutState.statusMessage) {
      const cls = checkoutState.statusKind === "error" ? "checkout-summary__error" : "checkout-summary__info";
      summary.appendChild(h("p", { class: cls }, checkoutState.statusMessage));
    }
  }

  function buildCheckoutPayload({ strict = false } = {}) {
    if (!checkoutRefs.form) return null;
    const name = (checkoutRefs.name?.value || "").trim();
    const email = (checkoutRefs.email?.value || "").trim();
    const phone = (checkoutRefs.phone?.value || "").trim();
    const street = (checkoutRefs.street?.value || "").trim();
    const postal = (checkoutRefs.postal?.value || "").trim();
    const city = (checkoutRefs.city?.value || "").trim();
    const instructions = (checkoutRefs.instructions?.value || "").trim();
    const note = (checkoutRefs.note?.value || "").trim();
    const saveAddress = !!checkoutRefs.saveAddress?.checked;
    const voucherCode = (checkoutRefs.voucher?.value || "").trim().toUpperCase();
    const paymentMethod = checkoutState.method || PAYMENT_METHODS[0].value;

    const missing = [];
    if (!name) missing.push("full name");
    if (!email) missing.push("email");
    if (!phone) missing.push("phone number");
    if (!street) missing.push("street");
    if (!postal) missing.push("postal code");
    if (!city) missing.push("city");
    const group = getCartGroup(checkoutState.restaurantId);
    if (!group || !group.items.length) missing.push("cart items");

    if (missing.length && strict) {
      toast("Please complete: " + missing.join(", "), "err");
      renderCheckoutSummary("Complete the required fields to continue.");
      return null;
    }
    if (missing.length) {
      return null;
    }

    const parts = name.split(" ").filter(Boolean);
    const first_name = parts.shift() || name;
    const last_name = parts.join(" ") || "";

    if (paymentMethod === "voucher" && !voucherCode) {
      checkoutState.statusMessage = "Voucher payment requires a voucher code.";
      checkoutState.statusKind = "error";
      if (strict) {
        toast("Enter a voucher code for voucher payments.", "err");
      }
      renderCheckoutSummary();
      return null;
    }

    const payload = {
      restaurant_id: group?.restaurant_id || null,
      items: (group?.items || []).map((i) => ({ menu_item_id: i.menu_item_id, quantity: i.quantity })),
      note_for_kitchen: note || null,
      address: {
        street,
        city,
        postal_code: postal,
        country: "DE",
        label: saveAddress ? "Checkout" : null,
        phone,
        instructions: instructions || null,
        save_address: saveAddress,
      },
      payment: {
        method: paymentMethod,
        voucher_code: voucherCode || null,
      },
    };

    const profile = {
      first_name,
      last_name,
      street,
      postal_code: postal,
      city,
      phone,
      email,
    };

    if (!payload.restaurant_id) {
      checkoutState.statusMessage = "Unable to determine restaurant for checkout.";
      checkoutState.statusKind = "error";
      if (strict) toast("Select a restaurant to checkout.", "err");
      renderCheckoutSummary();
      return null;
    }

    checkoutState.voucherCode = voucherCode;
    return { payload, profile };
  }

  async function updateCheckoutPreview({ showToast = false } = {}) {
    const built = buildCheckoutPayload();
    if (!built) {
      checkoutState.preview = null;
      checkoutState.statusMessage = "";
      renderCheckoutSummary();
      return false;
    }

    checkoutState.loading = true;
    checkoutState.statusMessage = "";
    checkoutState.statusKind = "info";
    renderCheckoutSummary();
    try {
      const preview = await API.checkout.preview(built.payload);
      checkoutState.preview = preview;
      const voucherCode = (checkoutRefs.voucher?.value || "").trim().toUpperCase();
      const voucherApplied = preview.breakdown.voucher_amount_cents > 0;
      if (voucherCode) {
        if (voucherApplied) {
          checkoutState.statusMessage = `Voucher applied: -${money(preview.breakdown.voucher_amount_cents)} (remaining due ${money(preview.breakdown.payment_due_cents)})`;
          checkoutState.statusKind = "info";
        } else {
          checkoutState.statusMessage = "Voucher code valid but no discount applied (check balance and payment method).";
          checkoutState.statusKind = "error";
        }
      } else {
        checkoutState.statusMessage = "";
        checkoutState.statusKind = "info";
      }
      renderCheckoutSummary();
      return true;
    } catch (err) {
      checkoutState.preview = null;
      if (err.status === 401 || err.status === 403) {
        checkoutState.statusMessage = "Please sign in to preview totals.";
        checkoutState.statusKind = "error";
        renderCheckoutSummary();
        toast("Please sign in to continue checkout.", "err");
        openAuthModal("login");
      } else {
        checkoutState.statusMessage = err.message || "Unable to calculate total.";
        checkoutState.statusKind = "error";
        renderCheckoutSummary();
        if (showToast) toast(err.message || "Preview failed", "err");
      }
      return false;
    } finally {
      checkoutState.loading = false;
    }
  }

  function buildCheckoutSheet() {
    const overlay = h("div", { class: "checkout-sheet" });
    const backdrop = h("div", { class: "checkout-sheet__backdrop" });
    backdrop.addEventListener("click", closeCheckoutSheet);

    const panel = h("div", { class: "checkout-sheet__panel", tabindex: "-1" });
    const header = h("div", { class: "checkout-sheet__header" },
      h("h2", {}, checkoutState.restaurant ? `Checkout • ${checkoutState.restaurant.name || ""}` : "Checkout"),
      h("button", { type: "button", class: "checkout-sheet__close", onclick: closeCheckoutSheet, "aria-label": "Close checkout" }, "×"),
    );

    const form = h("form", { class: "checkout-form" });
    checkoutRefs.form = form;

    const contactSection = h("section", { class: "checkout-section" },
      h("h3", {}, "Contact"),
      h("div", { class: "checkout-grid" },
        h("label", { class: "checkout-field" },
          h("span", { class: "checkout-field__label" }, "Full name"),
          checkoutRefs.name = h("input", { type: "text", autocomplete: "name", required: true, placeholder: "Jane Doe" })
        ),
        h("label", { class: "checkout-field" },
          h("span", { class: "checkout-field__label" }, "Email"),
          checkoutRefs.email = h("input", { type: "email", autocomplete: "email", required: true, placeholder: "jane@example.com" })
        ),
        h("label", { class: "checkout-field" },
          h("span", { class: "checkout-field__label" }, "Phone"),
          checkoutRefs.phone = h("input", { type: "tel", autocomplete: "tel", required: true, placeholder: "+49 ..." })
        ),
      )
    );

    const addressSection = h("section", { class: "checkout-section" },
      h("h3", {}, "Delivery address"),
      h("div", { class: "checkout-grid" },
        h("label", { class: "checkout-field checkout-field--wide" },
          h("span", { class: "checkout-field__label" }, "Street"),
          checkoutRefs.street = h("input", { type: "text", autocomplete: "address-line1", required: true, placeholder: "Street and house number" })
        ),
        h("label", { class: "checkout-field" },
          h("span", { class: "checkout-field__label" }, "Postal code"),
          checkoutRefs.postal = h("input", { type: "text", autocomplete: "postal-code", required: true, placeholder: "10115" })
        ),
        h("label", { class: "checkout-field" },
          h("span", { class: "checkout-field__label" }, "City"),
          checkoutRefs.city = h("input", { type: "text", autocomplete: "address-level2", required: true, placeholder: "Berlin" })
        ),
        h("label", { class: "checkout-field checkout-field--wide" },
          h("span", { class: "checkout-field__label" }, "Delivery instructions (optional)"),
          checkoutRefs.instructions = h("textarea", { rows: 2, placeholder: "Entry code, floor, etc." })
        ),
      ),
      h("label", { class: "checkout-checkbox" },
        checkoutRefs.saveAddress = h("input", { type: "checkbox", checked: true }),
        h("span", {}, "Save this address to my profile")
      )
    );

    const paymentOptionsWrap = h("div", { class: "checkout-payment-options" });
    PAYMENT_METHODS.forEach(({ value, label }) => {
      const input = h("input", {
        type: "radio",
        name: "checkout-payment",
        value,
        id: `checkout-payment-${value}`,
        checked: value === checkoutState.method,
      });
      const labelEl = h("label", { class: "checkout-payment-option" },
        input,
        h("span", {}, label)
      );
      if (value === checkoutState.method) labelEl.classList.add("is-selected");
      input.addEventListener("change", () => {
        if (!input.checked) return;
        checkoutState.method = value;
        paymentOptionsWrap.querySelectorAll(".checkout-payment-option").forEach((el) => el.classList.remove("is-selected"));
        labelEl.classList.add("is-selected");
        updateCheckoutPreview({ showToast: false });
      });
      paymentOptionsWrap.appendChild(labelEl);
    });

    const paymentSection = h("section", { class: "checkout-section" },
      h("h3", {}, "Payment"),
      paymentOptionsWrap,
      (() => {
        const voucherInput = checkoutRefs.voucher = h("input", {
          type: "text",
          placeholder: "Enter voucher (optional)",
          autocapitalize: "characters",
        });
        voucherInput.addEventListener("blur", () => {
          voucherInput.value = (voucherInput.value || "").trim().toUpperCase();
        });
        voucherInput.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") {
            ev.preventDefault();
            voucherInput.value = (voucherInput.value || "").trim().toUpperCase();
            updateCheckoutPreview({ showToast: true });
          }
        });
        const applyBtn = h("button", {
          type: "button",
          class: "checkout-voucher__apply",
          onclick: () => {
            voucherInput.value = (voucherInput.value || "").trim().toUpperCase();
            updateCheckoutPreview({ showToast: true });
          },
        }, "Apply");
        return h("div", { class: "checkout-voucher" },
          h("label", { class: "checkout-field checkout-field--wide" },
            h("span", { class: "checkout-field__label" }, "Voucher code"),
            h("div", { class: "checkout-voucher__row" },
              voucherInput,
              applyBtn,
            )
          )
        );
      })(),
      h("label", { class: "checkout-field checkout-field--wide" },
        h("span", { class: "checkout-field__label" }, "Note for kitchen (optional)"),
        checkoutRefs.note = h("textarea", { rows: 2, placeholder: "e.g. extra napkins, ring the bell twice" })
      ),
    );

    checkoutRefs.summary = h("div", { class: "checkout-summary" });

    checkoutRefs.submit = h("button", { type: "submit", class: "checkout-submit" }, "Place order");

    form.append(
      contactSection,
      addressSection,
      paymentSection,
      h("section", { class: "checkout-section checkout-section--summary" },
        h("h3", {}, "Order summary"),
        checkoutRefs.summary,
      ),
      h("div", { class: "checkout-actions" },
        checkoutRefs.submit,
        h("button", { type: "button", class: "checkout-cancel", onclick: closeCheckoutSheet }, "Cancel")
      ),
    );

    form.addEventListener("submit", handleCheckoutSubmit);

    panel.append(header, form);
    overlay.append(backdrop, panel);
    overlay.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") {
        ev.preventDefault();
        closeCheckoutSheet();
      }
    });
    setTimeout(() => panel.focus(), 0);
    return overlay;
  }

  async function handleCheckoutSubmit(ev) {
    ev.preventDefault();
    if (checkoutState.loading) return;

    const built = buildCheckoutPayload({ strict: true });
    if (!built) return;

    checkoutRefs.submit.disabled = true;
    const originalLabel = checkoutRefs.submit.textContent;
    checkoutRefs.submit.textContent = "Placing order…";

    try {
      await API.customers.update(built.profile);
      ME = { ...(ME || {}), ...built.profile };
    } catch (err) {
      checkoutRefs.submit.disabled = false;
      checkoutRefs.submit.textContent = originalLabel;
      toast(err.message || "Failed to update profile", "err");
      return;
    }

    const previewOk = await updateCheckoutPreview({ showToast: true });
    if (!previewOk) {
      checkoutRefs.submit.disabled = false;
      checkoutRefs.submit.textContent = originalLabel;
      return;
    }

    try {
      await API.checkout.submit(built.payload);
      toast("Order placed!");
      const finishedRid = checkoutState.restaurantId;
      closeCheckoutSheet();
      removeCartGroup(finishedRid);
      updateCartUI();
      openCart(false);
      renderOrders();
    } catch (err) {
      toast(err.message || "Checkout failed", "err");
      checkoutRefs.submit.disabled = false;
      checkoutRefs.submit.textContent = originalLabel;
    }
  }

  async function checkout(targetRestaurantId = null) {
    if (!token) { toast("Login as customer first", "err"); openAuthModal("login"); return; }

    const groups = getCartGroupsInOrder();
    if (!groups.length) return toast("Cart is empty", "err");

    let group = null;
    if (targetRestaurantId != null) {
      group = getCartGroup(targetRestaurantId);
    } else if (groups.length === 1) {
      group = groups[0];
    }

    if (!group || !group.items.length) {
      openCart(true);
      toast("Select a restaurant in the cart to checkout.", "err");
      return;
    }

    try {
      if (!ME) ME = await API.customers.me();
    } catch {
      // ignore; profile may still be completed during checkout
    }

    let restaurantDetails = group.restaurant;
    try {
      if (!restaurantDetails || !restaurantDetails.min_order_cents || !restaurantDetails.delivery_fee_cents) {
        restaurantDetails = await API.restaurants.detail(group.restaurant_id);
        if (restaurantDetails) {
          group.restaurant = restaurantDetails;
        }
      }
    } catch (err) {
      toast(err.message || "Could not load restaurant details", "err");
      return;
    }

    const subtotal = cartSubtotal(group.restaurant_id);
    if (restaurantDetails?.min_order_cents && subtotal < restaurantDetails.min_order_cents) {
      toast(`Minimum order is ${money(restaurantDetails.min_order_cents)}`, "err");
      return;
    }

    resetCheckoutState();
    checkoutState.restaurantId = group.restaurant_id;
    checkoutState.restaurant = restaurantDetails || null;
    checkoutSheet = buildCheckoutSheet();
    document.body.appendChild(checkoutSheet);
    document.body.style.overflow = "hidden";

    const fullName = [ME?.first_name, ME?.last_name].filter(Boolean).join(" ").trim();
    if (fullName) checkoutRefs.name.value = fullName;
    if (ME?.email) checkoutRefs.email.value = ME.email;
    if (ME?.phone) checkoutRefs.phone.value = ME.phone;
    if (ME?.street) checkoutRefs.street.value = ME.street;
    if (ME?.postal_code) checkoutRefs.postal.value = ME.postal_code;
    if (ME?.city) checkoutRefs.city.value = ME.city;

    renderCheckoutSummary();
    updateCheckoutPreview({ showToast: false });
  }

  // ========== Auth modal handlers ==========
  function openAuthModal(which = "login") {
    modal.classList.add("is-open");
    if (which === "register") {
      tabRegister.click();
    } else if (which === "profile") {
      tabProfile.click();
    } else {
      tabLogin.click();
    }
  }
  document.getElementById("auth-close")?.addEventListener("click", () => modal.classList.remove("is-open"));

  // Tab toggles (basic)
  tabLogin?.addEventListener("click", () => {
    tabLogin.classList.add("is-active"); tabRegister.classList.remove("is-active"); tabProfile.classList.remove("is-active");
    pnlLogin.classList.remove("hidden"); pnlRegister.classList.add("hidden"); pnlProfile.classList.add("hidden");
  });
  tabRegister?.addEventListener("click", () => {
    tabRegister.classList.add("is-active"); tabLogin.classList.remove("is-active"); tabProfile.classList.remove("is-active");
    pnlRegister.classList.remove("hidden"); pnlLogin.classList.add("hidden"); pnlProfile.classList.add("hidden");
  });
  tabProfile?.addEventListener("click", async () => {
    tabProfile.classList.add("is-active"); tabLogin.classList.remove("is-active"); tabRegister.classList.remove("is-active");
    pnlProfile.classList.remove("hidden"); pnlLogin.classList.add("hidden"); pnlRegister.classList.add("hidden");
    // load profile
    try { ME = await API.customers.me(); fillProfileForm(ME); } catch {}
  });

  function fillProfileForm(me) {
    if (!me) return;
    document.getElementById("me_name").value = [me.first_name, me.last_name].filter(Boolean).join(" ");
    document.getElementById("me_phone").value = me.phone || "";
    document.getElementById("me_email").value = me.email || "";
    document.getElementById("me_street").value = me.street || "";
    document.getElementById("me_plz").value = me.postal_code || "";
    document.getElementById("me_city").value = me.city || "";
  }

  // Login submit
  pnlLogin?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("login_email").value.trim();
    const password = document.getElementById("login_password").value;
    if (!email || !password) return toast("Enter email and password", "err");
    try {
      const data = await API.auth.loginCustomer(email, password);
      saveToken(data.access_token);
      updateAuthUI();
      modal.classList.remove("is-open");
      toast("Welcome back!");
      renderHome();
    } catch (err) {
      toast(err.message || "Login failed", "err");
    }
  });

  // Register submit
  pnlRegister?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      name: document.getElementById("reg_name").value.trim(), // full name (split below)
      phone: document.getElementById("reg_phone").value.trim(),
      email: document.getElementById("reg_email").value.trim(),
      street: document.getElementById("reg_street").value.trim(),
      postal_code: document.getElementById("reg_plz").value.trim(),
      city: document.getElementById("reg_city").value.trim(),
      password: document.getElementById("reg_password").value,
    };
    if (!payload.email || !payload.password || !payload.name) return toast("Fill required fields", "err");
    const [first_name, ...rest] = payload.name.split(" ");
    const last_name = rest.join(" ");
    try {
      const data = await API.auth.registerCustomer({ ...payload, first_name, last_name });
      saveToken(data.access_token);
      updateAuthUI();
      modal.classList.remove("is-open");
      toast("Account created!");
      renderHome();
    } catch (err) {
      toast(err.message || "Registration failed", "err");
    }
  });

  // Profile save
  pnlProfile?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const full = document.getElementById("me_name").value.trim();
    const [first_name, ...rest] = full.split(" ");
    const last_name = rest.join(" ");
    const payload = {
      first_name,
      last_name,
      phone: document.getElementById("me_phone").value.trim(),
      email: document.getElementById("me_email").value.trim(),
      street: document.getElementById("me_street").value.trim(),
      postal_code: document.getElementById("me_plz").value.trim(),
      city: document.getElementById("me_city").value.trim(),
    };
    try {
      await API.customers.update(payload);
      toast("Profile saved");
      modal.classList.remove("is-open");
    } catch (e1) { toast(e1.message || "Save failed", "err"); }
  });

  // ========== Header actions ==========
  if (btnLoginCust) btnLoginCust.onclick = () => openAuthModal("login");
  if (btnRegisterCust) btnRegisterCust.onclick = () => openAuthModal("register");

  // send owners to the dedicated dashboard page (with auth tabs inside)
  if (btnLoginRest) btnLoginRest.onclick = () => (window.location.href = "restaurant-dashboard.html#auth?tab=login");
  if (btnRegisterRest) btnRegisterRest.onclick = () => (window.location.href = "restaurant-dashboard.html#auth?tab=register");

  if (btnLogout) btnLogout.onclick = () => {
    saveToken("");
    updateAuthUI();
    toast("Logged out");
    renderHome();
    renderHomeDeals();
  };
  // ========== Top nav ==========
  const _navHome = document.getElementById("nav-home");
  const _navRests = document.getElementById("nav-restaurants");
  const _navOrders = document.getElementById("nav-orders");
  const _navWallet = document.getElementById("nav-wallet");
  if (_navHome)   _navHome.onclick   = () => { location.hash = "#home"; };
  if (_navRests)  _navRests.onclick  = () => { location.hash = "#restaurants"; };
  if (_navOrders) _navOrders.onclick = () => { location.hash = "#orders"; };
  if (_navWallet) _navWallet.onclick = () => { location.hash = "#wallet"; };
  // ========== Search form ==========
  const lastPLZ = localStorage.getItem("last_plz") || "";
  const lastRadius = localStorage.getItem("last_radius_km") || (searchRadiusSelect?.value || "5");
  if (lastPLZ) {
    searchInput.value = lastPLZ;
    if (currentLoc) {
      const radiusLabel = lastRadius ? ` • ${lastRadius} km` : "";
      currentLoc.textContent = `📍 PLZ ${lastPLZ}${radiusLabel}`;
    }
  }
  if (searchRadiusSelect) {
    searchRadiusSelect.value = lastRadius;
    searchRadiusSelect.addEventListener("change", () => {
      localStorage.setItem("last_radius_km", searchRadiusSelect.value || "5");
      if (currentLoc) {
        const plz = searchInput.value.trim();
        const radiusLabel = searchRadiusSelect.value ? ` • ${searchRadiusSelect.value} km` : "";
        currentLoc.textContent = plz ? `📍 PLZ ${plz}${radiusLabel}` : "📍 Set your PLZ";
      }
      const livePlz = searchInput.value.trim() || localStorage.getItem("last_plz") || "";
      if (isValidPlz(livePlz)) {
        performPlzSearch(livePlz);
      }
    });
  }

  function performPlzSearch(plz) {
    if (!isValidPlz(plz)) return;
    const sanitized = plz.trim();
    localStorage.setItem("last_plz", sanitized);
    if (searchRadiusSelect) {
      localStorage.setItem("last_radius_km", searchRadiusSelect.value || "5");
    }
    if (currentLoc) {
      const radiusLabel = searchRadiusSelect?.value ? ` • ${searchRadiusSelect.value} km` : "";
      currentLoc.textContent = `📍 PLZ ${sanitized}${radiusLabel}`;
    }
    if (searchInput && searchInput.value !== sanitized) {
      searchInput.value = sanitized;
    }
    const radius = searchRadiusSelect ? Number(searchRadiusSelect.value) : undefined;
    if ((location.hash || "").toLowerCase() !== "#restaurants") {
      location.hash = "#restaurants";
    } else {
      renderRestaurantSearch(sanitized, radius);
    }
  }

  searchForm?.addEventListener("submit", (e) => {
    e.preventDefault();
    const plz = searchInput.value.trim();
    if (!plz) return toast("Enter a PLZ to search", "err");
    if (!isValidPlz(plz)) return toast("PLZ must be 5 digits", "err");
    performPlzSearch(plz);
  });

  const debouncedHeaderSearch = debounce(() => {
    const plz = searchInput?.value?.trim();
    if (!isValidPlz(plz)) return;
    performPlzSearch(plz);
  }, 350);

  searchInput?.addEventListener("input", debouncedHeaderSearch);

  const triggerLiveFilters = () => {
    const plz = (searchInput?.value || localStorage.getItem("last_plz") || "").trim();
    if (!isValidPlz(plz)) {
      const now = Date.now();
      if (now - lastFilterToastAt > 1500) {
        toast("Enter a 5-digit PLZ first", "err");
        lastFilterToastAt = now;
      }
      return;
    }
    performPlzSearch(plz);
  };

  const wireSidebarFilters = () => {
    document.querySelectorAll(".sidebar input").forEach((inp) => {
      if (inp.dataset.liveBound) return;
      inp.addEventListener("change", triggerLiveFilters);
      inp.dataset.liveBound = "1";
    });
    document.querySelectorAll(".search-sort select").forEach((sel) => {
      if (sel.dataset.liveBound) return;
      sel.addEventListener("change", triggerLiveFilters);
      sel.dataset.liveBound = "1";
    });
  };

  wireSidebarFilters();
  // ========== Deals rail on home ==========
  function dealCard(rest) {
    const card = document.createElement("div"); card.className = "card clickable";
    const img = document.createElement("div"); img.className = "card-image";
    img.style.backgroundImage = rest.image_url ? `url('${rest.image_url}')` : "linear-gradient(135deg,#f4f4f4,#e9e9e9)";
    const content = document.createElement("div"); content.className = "card-content";
    const title = document.createElement("div"); title.className = "card-title"; title.textContent = rest.name || "Restaurant";
    const details = document.createElement("div"); details.className = "card-details";
    const prep = rest.prep_time_min ?? 20;
    const rating = getRestaurantRating(rest);
    const ratingLabel = rating != null ? `${rating.toFixed(1)} ★` : "New";
    details.innerHTML = `<span class="card-rating">${ratingLabel}</span><span>•</span><span>${prep}–${prep + 10} min</span>`;
    const del = document.createElement("div"); del.className = "card-delivery";
    const fee = (rest.delivery_fee_cents ?? 0) / 100; del.innerHTML = `<span>${fee.toFixed(2)}€ delivery</span><span class="free-delivery">${fee === 0 ? "Free delivery" : "&nbsp;"}</span>`;
    content.appendChild(title);
    if (rest.description) {
      const p = document.createElement("p");
      p.style.color = "#666"; p.style.margin = "4px 0 10px"; p.textContent = rest.description;
      content.appendChild(p);
    }
    content.appendChild(details); content.appendChild(del);
    card.appendChild(img); card.appendChild(content);
    card.addEventListener("click", () => { location.hash = `#restaurant/${rest.id}`; });
    return card;
  }
  async function renderHomeDeals() {
    const grid = document.getElementById("deals-grid");
    if (!grid) return;
    grid.innerHTML = "<div style='opacity:.6'>Loading…</div>";
    try {
      const all = await API.restaurants.list({ all: true });
      grid.innerHTML = "";
      if (!all.length) return (grid.innerHTML = "<div style='opacity:.6'>No restaurants found.</div>");
      all.forEach((r) => grid.appendChild(dealCard(r)));
      const pc = document.getElementById("place-count"); if (pc) pc.textContent = `${all.length} places`;
    } catch (e) {
      grid.innerHTML = `<div style="color:#c00">${e?.message || "Load failed"}</div>`;
    }
  }
  // ========== Cart wiring ==========
  cartClose?.addEventListener("click", () => openCart(false));
  cartBtn?.addEventListener("click", () => openCart(!cartDrawer.classList.contains("is-open")));
  checkoutBtn?.addEventListener("click", () => checkout());
  // ========== Boot ==========
  restoreCartFromStorage();
  updateAuthUI();
  updateCartUI();

  let navDelegated = false;

  function ensureNavDelegation() {
    if (navDelegated) return;
    document.addEventListener("click", (e) => {
      const el = e.target && (e.target.closest ? e.target.closest('[data-nav-restaurant]') : null);
      if (!el) return;
      const rid = el.getAttribute("data-nav-restaurant");
      if (!rid) return;
      e.preventDefault();
      if (location.hash !== `#restaurant/${rid}`) {
        location.hash = `#restaurant/${rid}`;
      } else {
        renderRestaurant(parseInt(rid, 10));
      }
    });
    navDelegated = true;
  }

  function handleRoute() {
    ensureNavDelegation();
    const hash = (location.hash || "#home").toLowerCase();

    if (hash.startsWith("#restaurant/")) {
      const rid = parseInt(hash.split("/")[1], 10);
      if (rid) renderRestaurant(rid);
      return;
    }
    if (hash === "#restaurants") {
      const lp = localStorage.getItem("last_plz") || "";
      const lr = localStorage.getItem("last_radius_km");
      return renderRestaurantSearch(lp, lr ? Number(lr) : null);
    }
    if (hash === "#orders") {
      return renderOrders();
    }
    if (hash === "#wallet") {
      return renderWallet();
    }

    renderHome();
    renderHomeDeals();
  }

  handleRoute();
  window.addEventListener("hashchange", handleRoute);
