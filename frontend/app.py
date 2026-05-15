# -*- coding: utf-8 -*-
import os
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import requests

MSK_TZ = ZoneInfo("Europe/Moscow")
import streamlit as st
import folium
from streamlit_folium import st_folium

API_URL = os.getenv("API_URL", "http://localhost:8000")
st.set_page_config(page_title="Trip", page_icon="✈", layout="wide")

st.markdown("""<style>
.main .block-container{padding-top:1rem;max-width:1200px}

/* --- карточки маршрута (светлая тема) --- */
.leg-walk{background:#e8f5e9;border-left:4px solid #66bb6a;border-radius:6px;padding:.4rem .75rem;margin:.3rem 0;color:#1b5e20}
.leg-walk b{color:#1b5e20}
.leg-train{background:#e3f2fd;border-left:4px solid #42a5f5;border-radius:6px;padding:.4rem .75rem;margin:.3rem 0;color:#0d47a1}
.leg-train b{color:#0d47a1}
.leg-transfer{background:#fff8e1;border-left:4px solid #ffca28;border-radius:6px;padding:.25rem .75rem;margin:.15rem 0;font-size:.85em;color:#6d4c00}
.leg-wait{background:#f3e5f5;border-left:4px solid #ab47bc;border-radius:6px;padding:.25rem .75rem;margin:.15rem 0;font-size:.85em;color:#4a148c}
.route-header{background:#fafafa;border:1px solid #e0e0e0;border-radius:8px;padding:.6rem 1rem;margin-top:.5rem;color:#31333f}
.route-header b{color:#31333f}
.station-card{background:#f0f2f6;border-radius:8px;padding:.5rem .75rem;margin:.25rem 0;color:#31333f}
.station-card b{color:#31333f}
.train-no{background:#1565c0;color:#fff;border-radius:4px;padding:0 6px;font-weight:bold;font-size:.9em}
.train-time{color:#37474f;font-size:.88em}
.regularity{color:#546e7a;font-size:.8em;margin-top:2px}
.scheduled-tag{background:#2e7d32;color:#fff;border-radius:4px;padding:0 6px;font-size:.75em;margin-left:6px}

/* --- тёмная тема Streamlit --- */
[data-theme="dark"] .leg-walk,
.stApp[data-theme="dark"] .leg-walk{
  background:#1e3d2e;color:#c8e6c9;border-left-color:#66bb6a}
[data-theme="dark"] .leg-walk b,
.stApp[data-theme="dark"] .leg-walk b{color:#a5d6a7}

[data-theme="dark"] .leg-train,
.stApp[data-theme="dark"] .leg-train{
  background:#1a2e42;color:#bbdefb;border-left-color:#42a5f5}
[data-theme="dark"] .leg-train b,
.stApp[data-theme="dark"] .leg-train b{color:#90caf9}

[data-theme="dark"] .leg-transfer,
.stApp[data-theme="dark"] .leg-transfer{
  background:#3d3420;color:#ffe082;border-left-color:#ffca28}

[data-theme="dark"] .leg-wait,
.stApp[data-theme="dark"] .leg-wait{
  background:#2d1f33;color:#e1bee7;border-left-color:#ab47bc}

[data-theme="dark"] .route-header,
.stApp[data-theme="dark"] .route-header{
  background:#262730;color:#fafafa;border-color:#464646}
[data-theme="dark"] .route-header b,
.stApp[data-theme="dark"] .route-header b{color:#fafafa}

[data-theme="dark"] .station-card,
.stApp[data-theme="dark"] .station-card{
  background:#262730;color:#fafafa;border:1px solid #464646}
[data-theme="dark"] .station-card b,
.stApp[data-theme="dark"] .station-card b{color:#fafafa}

[data-theme="dark"] .train-time,
.stApp[data-theme="dark"] .train-time{color:#b0bec5}

[data-theme="dark"] .regularity,
.stApp[data-theme="dark"] .regularity{color:#9e9e9e}
</style>""", unsafe_allow_html=True)

st.markdown("## ✈ Путешествия — поиск маршрутов")

for k, v in {"search_data": None, "selected_route": 0,
             "setting_point": "A", "_lck": None, "_pend": None}.items():
    if k not in st.session_state:
        st.session_state[k] = v

for wk, wv in [("w_flat", 55.7558), ("w_flon", 37.6173),
               ("w_tlat", 59.9343), ("w_tlon", 30.3351)]:
    if wk not in st.session_state:
        st.session_state[wk] = wv

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
        return "<1 мин"
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} ч {m} мин"
    return f"{h} ч" if h else f"{m} мин"


COLORS = ["#1565c0", "#c62828", "#2e7d32", "#6a1b9a", "#e65100",
          "#00838f", "#4e342e", "#283593", "#bf360c", "#1b5e20"]

with st.sidebar:
    st.markdown("### 📍 Точки маршрута")
    st.markdown("**🟢 Точка А (откуда)**")
    from_lat = st.number_input("Широта А", format="%.6f", key="w_flat", step=0.01)
    from_lon = st.number_input("Долгота А", format="%.6f", key="w_flon", step=0.01)
    st.markdown("**🔴 Точка Б (куда)**")
    to_lat = st.number_input("Широта Б", format="%.6f", key="w_tlat", step=0.01)
    to_lon = st.number_input("Долгота Б", format="%.6f", key="w_tlon", step=0.01)
    st.divider()
    st.markdown("### 📅 Время отправления (МСК)")
    now = datetime.now(MSK_TZ)
    departure_date = st.date_input(
        "Дата",
        value=now.date(),
        min_value=date(2024, 1, 1),
        help="Если не указана — берём сегодняшнюю",
    )
    time_text = st.text_input(
        "Время (ЧЧ:ММ)",
        value=f"{now.hour:02d}:{now.minute:02d}",
        placeholder="08:30",
        help="Введите вручную в формате ЧЧ:ММ. Если пусто — берём текущее",
    )

    if not departure_date:
        departure_date = now.date()

    departure_time_value = time(now.hour, now.minute)
    text = (time_text or "").strip()
    if text:
        try:
            departure_time_value = datetime.strptime(text, "%H:%M").time()
        except ValueError:
            st.warning(f"⚠️ Неверный формат времени «{text}», используем текущее")
    st.divider()
    optimize_by = st.radio(
        "Оптимизация", ["time", "cost"],
        format_func=lambda x: "⏱ По времени" if x == "time" else "₽ По стоимости",
    )
    st.divider()
    setting = st.radio(
        "🖱 Клик по карте ставит:", ["A", "B"],
        format_func=lambda x: "🟢 Точку А" if x == "A" else "🔴 Точку Б",
        horizontal=True,
    )
    st.session_state.setting_point = setting
    st.divider()
    search_btn = st.button("🔍 Найти маршруты", use_container_width=True, type="primary")

if search_btn:
    payload = {
        "from_lat": from_lat, "from_lon": from_lon,
        "to_lat": to_lat, "to_lon": to_lon,
        "optimize_by": optimize_by,
        "departure_date": departure_date.isoformat() if departure_date else None,
        "departure_time": (departure_time_value.strftime("%H:%M")
                           if departure_time_value else None),
        "min_transfer_min": 15,
    }
    with st.spinner("Ищем маршруты..."):
        try:
            resp = requests.post(f"{API_URL}/search", json=payload, timeout=30)
            resp.raise_for_status()
            st.session_state.search_data = resp.json()
            st.session_state.selected_route = 0
        except requests.exceptions.RequestException as e:
            st.error(f"Ошибка API: {e}")

data = st.session_state.search_data
routes = data.get("routes", []) if data else []

if routes:
    labels = []
    for r in routes:
        dur = fmt_time(r["total_duration_min"])
        price = f'{r["total_price_rub"]:,.0f}'
        labels.append(f'Маршрут {r["id"]}: {dur}, {price} ₽')
    sel = st.selectbox(
        "🗺 Маршрут на карте:", range(len(routes)),
        format_func=lambda i: labels[i],
    )
    st.session_state.selected_route = sel

pn = "А (откуда)" if st.session_state.setting_point == "A" else "Б (куда)"
pe = "🟢" if st.session_state.setting_point == "A" else "🔴"
st.info(f"{pe} Кликните на карту, чтобы поставить точку **{pn}**")

m = folium.Map(
    location=[(from_lat + to_lat) / 2, (from_lon + to_lon) / 2],
    zoom_start=6, tiles="CartoDB positron",
)
fg = folium.FeatureGroup(name="fg")

folium.Marker(
    [from_lat, from_lon], tooltip="А — откуда",
    icon=folium.Icon(color="green", icon="play", prefix="fa"),
).add_to(fg)
folium.Marker(
    [to_lat, to_lon], tooltip="Б — куда",
    icon=folium.Icon(color="red", icon="stop", prefix="fa"),
).add_to(fg)

if data:
    for s in data.get("nearest_from", []):
        folium.CircleMarker(
            [s["lat"], s["lon"]], radius=7, color="#2e7d32",
            fill=True, fill_opacity=0.8,
            tooltip=f'{s["name"]} ({s["distance_m"]:,} м)',
        ).add_to(fg)
    for s in data.get("nearest_to", []):
        folium.CircleMarker(
            [s["lat"], s["lon"]], radius=7, color="#c62828",
            fill=True, fill_opacity=0.8,
            tooltip=f'{s["name"]} ({s["distance_m"]:,} м)',
        ).add_to(fg)
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
                folium.PolyLine(
                    pts, color="#66bb6a", weight=4,
                    dash_array="10 6", opacity=0.9,
                ).add_to(fg)
            elif leg["type"] == "train":
                folium.PolyLine(pts, color=clr, weight=5, opacity=0.85).add_to(fg)

m.fit_bounds([[min(from_lat, to_lat) - 0.5, min(from_lon, to_lon) - 0.5],
              [max(from_lat, to_lat) + 0.5, max(from_lon, to_lon) + 0.5]])

md = st_folium(m, feature_group_to_add=fg, width=None, height=520, key="map")

if md and md.get("last_clicked") is not None:
    c = md["last_clicked"]
    cl = round(c["lat"], 6)
    cn = round(c["lng"], 6)
    ck = f"{cl},{cn}"
    if ck != st.session_state._lck:
        st.session_state._lck = ck
        st.session_state._pend = {
            "pt": st.session_state.setting_point,
            "lat": cl, "lon": cn,
        }
        st.rerun()

if data:
    st.divider()

    dep_d = data.get("departure_date")
    dep_t = data.get("departure_time")
    if dep_d:
        prefix = f"📅 **Дата отправления:** {dep_d}"
        if dep_t:
            prefix += f" | ⏰ **Время:** {dep_t}"
        st.markdown(prefix)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### 🟢 Ближайшие к А")
        for s in data["nearest_from"]:
            st.markdown(
                f'<div class="station-card">• <b>{s["name"]}</b> '
                f'({s["uic_code"]}) — {s["distance_m"]:,} м</div>',
                unsafe_allow_html=True,
            )
    with c2:
        st.markdown("#### 🔴 Ближайшие к Б")
        for s in data["nearest_to"]:
            st.markdown(
                f'<div class="station-card">• <b>{s["name"]}</b> '
                f'({s["uic_code"]}) — {s["distance_m"]:,} м</div>',
                unsafe_allow_html=True,
            )
    st.divider()
    ol = "времени" if data["optimize_by"] == "time" else "стоимости"
    if routes:
        st.markdown(f"### Найдено маршрутов: {len(routes)} (по {ol})")
        for route in routes:
            ds = fmt_time(route["total_duration_min"])
            ps = f'{route["total_price_rub"]:,.0f}'
            tr = route.get("transfers", 0)
            tl = ("без пересадок" if tr == 0
                  else f"{tr} пересадка" if tr == 1
                  else f"{tr} пересадки")
            scheduled_tag = ('<span class="scheduled-tag">по расписанию</span>'
                             if route.get("scheduled") else "")
            idx = st.session_state.selected_route
            issel = route["id"] == routes[min(idx, len(routes) - 1)]["id"]
            brd = "border:2px solid #1565c0;" if issel else ""
            st.markdown(
                f'<div class="route-header" style="{brd}">'
                f'<b>Маршрут {route["id"]}</b>{scheduled_tag} | ⏱ {ds} | '
                f'₽ {ps} | {tl}</div>',
                unsafe_allow_html=True,
            )
            for leg in route["legs"]:
                if leg["type"] == "walk":
                    d = leg.get("distance_m", 0)
                    t = fmt_time(leg["duration_min"])
                    mode = leg.get("mode", "walk")
                    icon = "🚶" if mode == "walk" else "🚕"
                    label = "пешком" if mode == "walk" else "трансфер"
                    dist_label = (f'{d:,} м' if d < 1000
                                  else f'{d/1000:.1f} км')
                    st.markdown(
                        f'<div class="leg-walk">{icon} '
                        f'<b>{leg["from_name"]}</b> → <b>{leg["to_name"]}</b>'
                        f' — {label}, {dist_label}, ~{t}</div>',
                        unsafe_allow_html=True,
                    )
                elif leg["type"] == "train":
                    init_wait = leg.get("initial_wait_min")
                    transfer_wait = leg.get("transfer_wait_min")

                    if init_wait is not None and init_wait > 0:
                        st.markdown(
                            f'<div class="leg-wait">⌛ Ожидание поезда: '
                            f'{fmt_time(init_wait)}</div>',
                            unsafe_allow_html=True,
                        )
                    if transfer_wait is not None:
                        st.markdown(
                            f'<div class="leg-transfer">'
                            f'⏳ Пересадка ~{fmt_time(transfer_wait)}</div>',
                            unsafe_allow_html=True,
                        )

                    t = fmt_time(leg["duration_min"])
                    train_no = leg.get("train_no", "")
                    no_badge = (f'<span class="train-no">{train_no}</span> '
                                if train_no else "")

                    boarding_lbl = leg.get("boarding_label")
                    arrival_lbl = leg.get("arrival_label")
                    if boarding_lbl and arrival_lbl:
                        time_info = (f' <span class="train-time">'
                                     f'{boarding_lbl} → {arrival_lbl}</span>')
                    else:
                        time_info = ""

                    st.markdown(
                        f'<div class="leg-train">🚂 {no_badge}'
                        f'<b>{leg["from_name"]}</b> → <b>{leg["to_name"]}</b>'
                        f' — {t}, ₽ {leg["price_rub"]:,.0f}'
                        f'{time_info}</div>',
                        unsafe_allow_html=True,
                    )

                    reg_desc = leg.get("regularity_desc")
                    if reg_desc and reg_desc != "ежедневно":
                        st.markdown(
                            f'<div class="regularity">📆 {reg_desc}</div>',
                            unsafe_allow_html=True,
                        )
            st.markdown("")
    else:
        st.warning("Маршрутов не найдено.")
