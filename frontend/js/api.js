// js/api.js
(() => {
  // ---------- base + helpers ----------
  const getBase  = () => (typeof window.API_BASE !== "undefined" && window.API_BASE) || "http://127.0.0.1:8000";
  const getToken = () => localStorage.getItem("token") || "";
  const getSubject = () => localStorage.getItem("subject") || "";

  function localIsoNoMs(d = new Date()) {
    const dt = (d instanceof Date) ? d : new Date(d);
    const z = dt.getTimezoneOffset() * 60000;
    // return ISO without milliseconds but KEEP the trailing Z (UTC)
    return new Date(dt - z).toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  // Generic JSON request with optional cache-buster
  async function req(path, { method = "GET", json, headers = {}, cacheBust = true } = {}) {
    let url = path.startsWith("http") ? path : getBase() + path;

    if (method.toUpperCase() === "GET" && cacheBust) {
      url += (url.includes("?") ? "&" : "?") + "_ts=" + Date.now();
    }

    const res = await fetch(url, {
      method,
      headers: {
        Accept: "application/json",
        ...(json ? { "Content-Type": "application/json" } : {}),
        ...(getToken() ? { Authorization: "Bearer " + getToken() } : {}),
        ...headers,
      },
      body: json ? JSON.stringify(json) : undefined,
      cache: "no-store",
    });

    let data = null;
    try { data = await res.json(); } catch {}

    if (!res.ok) {
      const msg =
        data?.detail || data?.msg ||
        (Array.isArray(data) && data[0]?.msg) ||
        res.statusText || "Request failed";
      const err = new Error(msg);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  // ---------- API surface ----------
  const API = {
    req,

    auth: {
      // customers
      loginCustomer:   (email_or_name, password) => req("/api/auth/customer/login",    { method: "POST", json: { email_or_name, password } }),
      registerCustomer:(payload)                 => req("/api/auth/customer/register", { method: "POST", json: payload }),
      // restaurants (owner)
      loginRestaurant: (email_or_name, password) => req("/api/auth/restaurant/login",  { method: "POST", json: { email_or_name, password } }),
      registerRestaurant:(payload)               => req("/api/auth/restaurant/register",{ method: "POST", json: payload }),
    },

    customers: {
      me:     ()        => req("/api/customers/me"),
      update: (payload) => req("/api/customers/me", { method: "PATCH", json: payload }),
    },

    restaurants: {
      // Accepts either plz or postal_code (we send both to be backend-friendly)
      list: ({ plz, postal_code, nearby, all, now, free_delivery, min_order_max, halal, category, tag, new_within_days, radius_km } = {}) => {
        const url = new URL("/api/restaurants", getBase());
        if (plz)         url.searchParams.set("plz", String(plz).trim());
        if (postal_code) url.searchParams.set("plz", String(plz).trim());
        // if only one provided, mirror to the other key:
        if (plz) url.searchParams.set("plz", String(plz).trim());
        if (!plz && postal_code) url.searchParams.set("plz", String(postal_code).trim());

        if (nearby) url.searchParams.set("nearby", "true");
        if (all)    url.searchParams.set("all", "true");

        if (now !== undefined) {
          url.searchParams.set("now", localIsoNoMs(now));
        }
        if (free_delivery)   url.searchParams.set("free_delivery", "true");
        if (min_order_max!=null) url.searchParams.set("min_order_max", String(min_order_max));
        if (halal)           url.searchParams.set("halal", "true");
        if (category)        url.searchParams.set("category", String(category));
        if (tag)             url.searchParams.set("tag", String(tag));
        if (new_within_days!=null) url.searchParams.set("new_within_days", String(new_within_days));
        if (radius_km!=null) url.searchParams.set("radius_km", String(radius_km));
        return req(url.pathname + url.search);
      },

      detail: (rid)              => req(`/api/restaurants/${rid}`),
      update: (rid, body)        => req(`/api/restaurants/${rid}`, { method: "PATCH", json: body }),

      menu: {
        list:   (rid)            => req(`/api/restaurants/${rid}/menu-items`),
        create: (rid, body)      => req(`/api/restaurants/${rid}/menu-items`, { method: "POST",  json: body }),
        update: (rid, mid, body) => req(`/api/restaurants/${rid}/menu-items/${mid}`, { method: "PATCH", json: body }),
        remove: (rid, mid)       => req(`/api/restaurants/${rid}/menu-items/${mid}`, { method: "DELETE" }),
      },

      openingHours: {
        list:   (rid)            => req(`/api/restaurants/${rid}/opening-hours`),
        add:    (rid, body)      => req(`/api/restaurants/${rid}/opening-hours`, { method: "POST", json: body }),
        remove: (rid, ohid)      => req(`/api/restaurants/${rid}/opening-hours/${ohid}`, { method: "DELETE" }),
      },

      deliveryZips: {
        list:   (rid)            => req(`/api/restaurants/${rid}/delivery-zips`),
        add:    (rid, body)      => req(`/api/restaurants/${rid}/delivery-zips`, { method: "POST", json: body }),
        remove: (rid, dzid)      => req(`/api/restaurants/${rid}/delivery-zips/${dzid}`, { method: "DELETE" }),
      },
    },

    orders: {
      submit:   (payload)        => req("/api/orders", { method: "POST", json: payload }),
      mine:     ()               => {
        const sub = getSubject();
        if (sub?.startsWith("customer:")) {
          return req("/api/customers/me/orders");
        }
        if (sub?.startsWith("restaurant:")) {
          const rid = sub.split(":")[1];
          if (rid) return req(`/api/restaurants/${rid}/orders`);
        }
        return req("/api/orders");
      },
      detail:   (oid)            => req(`/api/orders/${oid}`),
      confirm:  (oid)            => req(`/api/orders/${oid}/confirm`,  { method: "POST" }),
      complete: (oid)            => req(`/api/orders/${oid}/complete`, { method: "POST" }),
      reject:   (oid)            => req(`/api/orders/${oid}/reject`,   { method: "POST" }),
      restaurantOrders: (rid)    => req(`/api/restaurants/${rid}/orders`),
    },

    checkout: {
      preview: (payload)        => req("/api/cart/preview", { method: "POST", json: payload }),
      submit:  (payload)        => req("/api/checkout", { method: "POST", json: payload }),
      redeemVoucher: (code, amount_cents = null) =>
        req("/api/vouchers/redeem", {
          method: "POST",
          json: { code, amount_cents },
        }),
    },

    wallet: {
      me:   ()                   => req("/api/wallet/me"),
      txns: (limit = 20)         => req(`/api/wallet/txns?limit=${encodeURIComponent(limit)}`),
      topup:(amount_cents)       => req("/api/wallet/topup", { method: "POST", json: { amount_cents } }),
    },

    discovery: {
      nearby: (plz, radius_m=2500)=> req(`/api/discovery/nearby?plz=${encodeURIComponent(plz)}&radius_m=${radius_m}`),
      place:  (place_id)           => req(`/api/discovery/place/${encodeURIComponent(place_id)}`),
    },

    ws: {
      restaurant: (rid) => getBase().replace(/^http/, "ws") + `/ws/restaurants/${rid}`,
    },
  };

  // Optional alias for your other script (if you still use it anywhere)
  API.public = { listRestaurants: (args) => API.restaurants.list(args) };

  window.API = API;
})();
