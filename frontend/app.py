# -*- coding: utf-8 -*-
import os
import requests
import streamlit as st
import folium
from streamlit_folium import st_folium

API_URL = os.getenv("API_URL", "http://localhost:8000")
st.set_page_config(page_title="Trip", page_icon="\u2708", layout="wide")

st.markdown("""<style>
.main .block-container{padding-top:1rem;max-width:1200px}
.leg-walk{background:#e8f5e9;border-left:4px solid #66bb6a;border-radius:6px;padding:.4rem .75rem;margin:.3rem 0}
.leg-train{background:#e3f2fd;border-left:4px solid #42a5f5;border-radius:6px;padding:.4rem .75rem;margin:.3rem 0}
.leg-transfer{background:#fff8e1;border-left:4px solid #ffca28;border-radius:6px;padding:.25rem .75rem;margin:.15rem 0;font-size:.85em;color:#6d4c00}
.route-header{background:#fafafa;border:1px solid #e0e0e0;border-radius:8px;padding:.6rem 1rem;margin-top:.5rem}
.station-card{background:#f0f2f6;border-radius:8px;padding:.5rem .75rem;margin:.25rem 0}
</style>""", unsafe_allow_html=True)

st.markdown("## \u2708 \u041f\u0443\u0442\u0435\u0448\u0435\u0441\u0442\u0432\u0438\u044f \u2014 \u043f\u043e\u0438\u0441\u043a \u043c\u0430\u0440\u0448\u0440\u0443\u0442\u043e\u0432")

# -- Session state init --
for k, v in {"search_data": None, "selected_route": 0,
             "setting_point": "A", "_lck": None, "_pend": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# Init widget keys with defaults (only once)
for wk, wv in [("w_flat", 55.7558), ("w_flon", 37.6173),
               ("w_tlat", 59.9343), ("w_tlon", 30.3351)]:
    if wk not in st.session_state:
        st.session_state[wk] = wv

# Apply pending click BEFORE widgets render
if st.session_state._pend is not None:
    p = st.session_state._pend
    st.session_state._pend = None
    if p["pt"] == "A":
        st.session_state.w_flat = p["lat"]
        st.session_state.w_flon = p["lon"]
    else:
        st.session_state.w_tlat = p["lat"]
        st.session_state.w_tlon = p["lon"]


def fmt_time(minutes):
    minutes = int(minutes)
    if minutes < 1:
        return "<1 \u043c\u0438\u043d"
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} \u0447 {m} \u043c\u0438\u043d"
    return f"{h} \u0447" if h else f"{m} \u043c\u0438\u043d"


COLORS = ["#1565c0", "#c62828", "#2e7d32", "#6a1b9a", "#e65100",
          "#00838f", "#4e342e", "#283593", "#bf360c", "#1b5e20"]

# -- Sidebar --
with st.sidebar:
    st.markdown("### \U0001f4cd \u0422\u043e\u0447\u043a\u0438 \u043c\u0430\u0440\u0448\u0440\u0443\u0442\u0430")
    st.markdown("**\U0001f7e2 \u0422\u043e\u0447\u043a\u0430 \u0410 (\u043e\u0442\u043a\u0443\u0434\u0430)**")
    from_lat = st.number_input("\u0428\u0438\u0440\u043e\u0442\u0430 \u0410", format="%.6f", key="w_flat", step=0.01)
    from_lon = st.number_input("\u0414\u043e\u043b\u0433\u043e\u0442\u0430 \u0410", format="%.6f", key="w_flon", step=0.01)
    st.markdown("**\U0001f534 \u0422\u043e\u0447\u043a\u0430 \u0411 (\u043a\u0443\u0434\u0430)**")
    to_lat = st.number_input("\u0428\u0438\u0440\u043e\u0442\u0430 \u0411", format="%.6f", key="w_tlat", step=0.01)
    to_lon = st.number_input("\u0414\u043e\u043b\u0433\u043e\u0442\u0430 \u0411", format="%.6f", key="w_tlon", step=0.01)
    st.divider()
    optimize_by = st.radio("\u041e\u043f\u0442\u0438\u043c\u0438\u0437\u0430\u0446\u0438\u044f", ["time", "cost"],
        format_func=lambda x: "\u23f1 \u041f\u043e \u0432\u0440\u0435\u043c\u0435\u043d\u0438" if x == "time" else "\u20bd \u041f\u043e \u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438")
    st.divider()
    setting = st.radio("\U0001f5b1 \u041a\u043b\u0438\u043a \u043f\u043e \u043a\u0430\u0440\u0442\u0435 \u0441\u0442\u0430\u0432\u0438\u0442:", ["A", "B"],
        format_func=lambda x: "\U0001f7e2 \u0422\u043e\u0447\u043a\u0443 \u0410" if x == "A" else "\U0001f534 \u0422\u043e\u0447\u043a\u0443 \u0411",
        horizontal=True)
    st.session_state.setting_point = setting
    st.divider()
    search_btn = st.button("\U0001f50d \u041d\u0430\u0439\u0442\u0438 \u043c\u0430\u0440\u0448\u0440\u0443\u0442\u044b", use_container_width=True, type="primary")

# -- Search --
if search_btn:
    payload = {"from_lat": from_lat, "from_lon": from_lon,
               "to_lat": to_lat, "to_lon": to_lon, "optimize_by": optimize_by}
    with st.spinner("\u0418\u0449\u0435\u043c \u043c\u0430\u0440\u0448\u0440\u0443\u0442\u044b..."):
        try:
            resp = requests.post(f"{API_URL}/search", json=payload, timeout=30)
            resp.raise_for_status()
            st.session_state.search_data = resp.json()
            st.session_state.selected_route = 0
        except requests.exceptions.RequestException as e:
            st.error(f"\u041e\u0448\u0438\u0431\u043a\u0430 API: {e}")

data = st.session_state.search_data
routes = data.get("routes", []) if data else []

if routes:
    labels = []
    for r in routes:
        dur = fmt_time(r["total_duration_min"])
        price = f'{r["total_price_rub"]:,.0f}'
        labels.append(f'\u041c\u0430\u0440\u0448\u0440\u0443\u0442 {r["id"]}: {dur}, {price} \u20bd')
    sel = st.selectbox("\U0001f5fa \u041c\u0430\u0440\u0448\u0440\u0443\u0442 \u043d\u0430 \u043a\u0430\u0440\u0442\u0435:", range(len(routes)),
                       format_func=lambda i: labels[i])
    st.session_state.selected_route = sel

pn = "\u0410 (\u043e\u0442\u043a\u0443\u0434\u0430)" if st.session_state.setting_point == "A" else "\u0411 (\u043a\u0443\u0434\u0430)"
pe = "\U0001f7e2" if st.session_state.setting_point == "A" else "\U0001f534"
st.info(f"{pe} \u041a\u043b\u0438\u043a\u043d\u0438\u0442\u0435 \u043d\u0430 \u043a\u0430\u0440\u0442\u0443, \u0447\u0442\u043e\u0431\u044b \u043f\u043e\u0441\u0442\u0430\u0432\u0438\u0442\u044c \u0442\u043e\u0447\u043a\u0443 **{pn}**")

# -- Map --
m = folium.Map(location=[(from_lat + to_lat) / 2, (from_lon + to_lon) / 2],
               zoom_start=6, tiles="CartoDB positron")
fg = folium.FeatureGroup(name="fg")

folium.Marker([from_lat, from_lon], tooltip="\u0410 \u2014 \u043e\u0442\u043a\u0443\u0434\u0430",
              icon=folium.Icon(color="green", icon="play", prefix="fa")).add_to(fg)
folium.Marker([to_lat, to_lon], tooltip="\u0411 \u2014 \u043a\u0443\u0434\u0430",
              icon=folium.Icon(color="red", icon="stop", prefix="fa")).add_to(fg)

if data:
    for s in data.get("nearest_from", []):
        folium.CircleMarker([s["lat"], s["lon"]], radius=7, color="#2e7d32",
            fill=True, fill_opacity=0.8,
            tooltip=f'{s["name"]} ({s["distance_m"]:,} \u043c)').add_to(fg)
    for s in data.get("nearest_to", []):
        folium.CircleMarker([s["lat"], s["lon"]], radius=7, color="#c62828",
            fill=True, fill_opacity=0.8,
            tooltip=f'{s["name"]} ({s["distance_m"]:,} \u043c)').add_to(fg)
    if routes:
        idx = st.session_state.selected_route
        route = routes[min(idx, len(routes) - 1)]
        clr = COLORS[idx % len(COLORS)]
        for leg in route["legs"]:
            fl = leg.get("from_lat")
            fln = leg.get("from_lon")
            tl = leg.get("to_lat")
            tln = leg.get("to_lon")
            if fl is None or tl is None:
                continue
            pts = [[fl, fln], [tl, tln]]
            if leg["type"] == "walk":
                folium.PolyLine(pts, color="#66bb6a", weight=4,
                    dash_array="10 6", opacity=0.9).add_to(fg)
            elif leg["type"] == "train":
                folium.PolyLine(pts, color=clr, weight=5, opacity=0.85).add_to(fg)

m.fit_bounds([[min(from_lat, to_lat) - 0.5, min(from_lon, to_lon) - 0.5],
              [max(from_lat, to_lat) + 0.5, max(from_lon, to_lon) + 0.5]])

md = st_folium(m, feature_group_to_add=fg, width=None, height=520, key="map")

# -- Handle click --
if md and md.get("last_clicked") is not None:
    c = md["last_clicked"]
    cl = round(c["lat"], 6)
    cn = round(c["lng"], 6)
    ck = f"{cl},{cn}"
    if ck != st.session_state._lck:
        st.session_state._lck = ck
        st.session_state._pend = {"pt": st.session_state.setting_point,
                                  "lat": cl, "lon": cn}
        st.rerun()

# -- Results --
if data:
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### \U0001f7e2 \u0411\u043b\u0438\u0436\u0430\u0439\u0448\u0438\u0435 \u043a \u0410")
        for s in data["nearest_from"]:
            st.markdown(f'<div class="station-card">\u2022 <b>{s["name"]}</b> '
                f'({s["uic_code"]}) \u2014 {s["distance_m"]:,} \u043c</div>',
                unsafe_allow_html=True)
    with c2:
        st.markdown("#### \U0001f534 \u0411\u043b\u0438\u0436\u0430\u0439\u0448\u0438\u0435 \u043a \u0411")
        for s in data["nearest_to"]:
            st.markdown(f'<div class="station-card">\u2022 <b>{s["name"]}</b> '
                f'({s["uic_code"]}) \u2014 {s["distance_m"]:,} \u043c</div>',
                unsafe_allow_html=True)
    st.divider()
    ol = "\u0432\u0440\u0435\u043c\u0435\u043d\u0438" if data["optimize_by"] == "time" else "\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u0438"
    if routes:
        st.markdown(f"### \u041d\u0430\u0439\u0434\u0435\u043d\u043e \u043c\u0430\u0440\u0448\u0440\u0443\u0442\u043e\u0432: {len(routes)} (\u043f\u043e {ol})")
        for route in routes:
            ds = fmt_time(route["total_duration_min"])
            ps = f'{route["total_price_rub"]:,.0f}'
            tr = route.get("transfers", 0)
            tl = "\u0431\u0435\u0437 \u043f\u0435\u0440\u0435\u0441\u0430\u0434\u043e\u043a" if tr == 0 else f"{tr} \u043f\u0435\u0440\u0435\u0441\u0430\u0434\u043a\u0430" if tr == 1 else f"{tr} \u043f\u0435\u0440\u0435\u0441\u0430\u0434\u043a\u0438"
            idx = st.session_state.selected_route
            issel = route["id"] == routes[min(idx, len(routes) - 1)]["id"]
            brd = "border:2px solid #1565c0;" if issel else ""
            st.markdown(f'<div class="route-header" style="{brd}">'
                f'<b>\u041c\u0430\u0440\u0448\u0440\u0443\u0442 {route["id"]}</b> | \u23f1 {ds} | '
                f'\u20bd {ps} | {tl}</div>', unsafe_allow_html=True)
            for leg in route["legs"]:
                if leg["type"] == "walk":
                    d = leg.get("distance_m", 0)
                    t = fmt_time(leg["duration_min"])
                    st.markdown(f'<div class="leg-walk">\U0001f6b6 '
                        f'<b>{leg["from_name"]}</b> \u2192 <b>{leg["to_name"]}</b>'
                        f' \u2014 {d:,} \u043c, ~{t}</div>', unsafe_allow_html=True)
                elif leg["type"] == "train":
                    w = leg.get("transfer_wait_min")
                    if w:
                        st.markdown(f'<div class="leg-transfer">'
                            f'\u23f3 \u041f\u0435\u0440\u0435\u0441\u0430\u0434\u043a\u0430 ~{w} \u043c\u0438\u043d</div>',
                            unsafe_allow_html=True)
                    t = fmt_time(leg["duration_min"])
                    st.markdown(f'<div class="leg-train">\U0001f682 '
                        f'<b>{leg["from_name"]}</b> \u2192 <b>{leg["to_name"]}</b>'
                        f' \u2014 {t}, \u20bd {leg["price_rub"]:,.0f}</div>',
                        unsafe_allow_html=True)
            st.markdown("")
    else:
        st.warning("\u041c\u0430\u0440\u0448\u0440\u0443\u0442\u043e\u0432 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e.")
