import os
from flask import Flask, render_template, request, redirect, url_for, jsonify
import requests
import json
import math
from models import db, OrderRequest, RequestItem, Vehicle, Route, Product, LoadPlan
import packing

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///logist.db'
app.config['SECRET_KEY'] = 'dev-secret-123'

# Яндекс.Карты API ключ (необязательно). Если не задан, используется Leaflet + OSRM.
app.config['YANDEX_MAPS_API_KEY'] = '701850c2-981b-4999-befb-22881237994f'

db.init_app(app)

# ------------------ Геокодирование ------------------
def geocode(address):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": address, "format": "json", "limit": 1}
    headers = {"User-Agent": "LogistMVP/1.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=5)
        data = resp.json()
        if data:
            return float(data[0]['lat']), float(data[0]['lon'])
    except:
        pass
    return None, None

@app.route('/api/geocode', methods=['POST'])
def api_geocode():
    addr = request.json.get('address', '')
    lat, lon = geocode(addr)
    if lat:
        return jsonify({'lat': lat, 'lon': lon})
    return jsonify({'error': 'Not found'}), 404

# ------------------ Поиск товаров ------------------
@app.route('/api/search_product')
def search_product():
    q = request.args.get('q', '').lower()
    products = Product.query.all()
    results = []
    for p in products:
        if q in p.name.lower() or q in (p.article or '').lower():
            results.append({
                'id': p.id,
                'article': p.article,
                'name': p.name,
                'weight': p.weight,
                'length': p.length,
                'width': p.width,
                'height': p.height,
                'package_type': p.package_type
            })
    return jsonify(results[:20])

# ------------------ Маршрутизация ------------------
def get_route_osrm(waypoints):
    coords = ";".join([f"{lon},{lat}" for lat, lon in waypoints])
    url = f"http://router.project-osrm.org/route/v1/driving/{coords}"
    params = {"overview": "full", "geometries": "geojson", "steps": "true"}
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        if data['code'] == 'Ok':
            return data
    except:
        pass
    return None

def axle_distribution(vehicle_length, positions, max_payload):
    if not positions or vehicle_length == 0:
        return 0, 0
    total_weight = sum(w for _, w in positions)
    sum_moment = sum(x * w for x, w in positions)
    cm = sum_moment / total_weight if total_weight > 0 else 0
    rear_axle_pos = vehicle_length
    rear_weight = total_weight * (cm / rear_axle_pos)
    front_weight = total_weight - rear_weight
    return round(front_weight, 2), round(rear_weight, 2)

def pallets_needed(item, vehicle):
    if not vehicle.pallet_length or not vehicle.pallet_width:
        return 1
    pallet_area = vehicle.pallet_length * vehicle.pallet_width
    pallet_max_height = vehicle.height
    pallet_volume = pallet_area * pallet_max_height
    total_vol = item.total_volume
    if total_vol <= 0:
        return 1
    n = math.ceil(total_vol / pallet_volume)
    return max(1, n)

# ------------------ Главная ------------------
@app.route('/')
def index():
    unassigned = OrderRequest.query.filter_by(status='new').all()
    vehicles = Vehicle.query.filter_by(status='available').all()
    routes = Route.query.order_by(Route.id.desc()).limit(10).all()
    return render_template('index.html', unassigned=unassigned, vehicles=vehicles, routes=routes)

# ------------------ CRUD товаров ------------------
@app.route('/products')
def list_products():
    products = Product.query.order_by(Product.name).all()
    return render_template('products.html', products=products)

@app.route('/product/new', methods=['GET','POST'])
def new_product():
    if request.method == 'POST':
        p = Product(
            article=request.form.get('article',''),
            name=request.form['name'],
            weight=float(request.form['weight']),
            length=float(request.form['length']),
            width=float(request.form['width']),
            height=float(request.form['height']),
            package_type=request.form.get('package_type','упак.')
        )
        db.session.add(p)
        db.session.commit()
        return redirect(url_for('list_products'))
    return render_template('product_form.html', product=None)

@app.route('/product/<int:id>/edit', methods=['GET','POST'])
def edit_product(id):
    p = Product.query.get_or_404(id)
    if request.method == 'POST':
        p.article = request.form.get('article','')
        p.name = request.form['name']
        p.weight = float(request.form['weight'])
        p.length = float(request.form['length'])
        p.width = float(request.form['width'])
        p.height = float(request.form['height'])
        p.package_type = request.form.get('package_type','упак.')
        db.session.commit()
        return redirect(url_for('list_products'))
    return render_template('product_form.html', product=p)

@app.route('/product/<int:id>/delete', methods=['POST'])
def delete_product(id):
    p = Product.query.get_or_404(id)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for('list_products'))

# ------------------ CRUD заявок ------------------
@app.route('/requests')
def list_requests():
    all_req = OrderRequest.query.order_by(OrderRequest.id.desc()).all()
    return render_template('requests.html', requests=all_req)

@app.route('/request/new', methods=['GET', 'POST'])
def new_request():
    if request.method == 'POST':
        req = OrderRequest(
            sender_name=request.form['sender_name'],
            sender_address=request.form['sender_address'],
            receiver_name=request.form['receiver_name'],
            receiver_address=request.form['receiver_address'],
            delivery_date=request.form.get('delivery_date', '')
        )
        req.sender_lat, req.sender_lon = geocode(req.sender_address)
        req.receiver_lat, req.receiver_lon = geocode(req.receiver_address)
        db.session.add(req)
        db.session.flush()

        cargo_names = request.form.getlist('cargo_name[]')
        quantities = request.form.getlist('quantity[]')
        weights = request.form.getlist('weight[]')
        lengths = request.form.getlist('length[]')
        widths = request.form.getlist('width[]')
        heights = request.form.getlist('height[]')
        product_ids = request.form.getlist('product_id[]')

        for i in range(len(cargo_names)):
            qty = int(quantities[i]) if quantities[i] else 1
            w = float(weights[i])
            l = float(lengths[i])
            wd = float(widths[i])
            h = float(heights[i])
            total_vol = l * wd * h * qty
            total_w = w * qty
            item = RequestItem(
                order_request_id=req.id,
                product_id=product_ids[i] if product_ids[i] else None,
                cargo_name=cargo_names[i],
                quantity=qty,
                length=l,
                width=wd,
                height=h,
                weight=w,
                total_volume=total_vol,
                total_weight=total_w
            )
            db.session.add(item)
        db.session.commit()
        return redirect(url_for('list_requests'))

    products = Product.query.order_by(Product.name).all()
    return render_template('request_form.html', request_obj=None, products=products)

@app.route('/request/<int:id>/edit', methods=['GET', 'POST'])
def edit_request(id):
    req = OrderRequest.query.get_or_404(id)
    if request.method == 'POST':
        req.sender_name = request.form['sender_name']
        req.sender_address = request.form['sender_address']
        req.receiver_name = request.form['receiver_name']
        req.receiver_address = request.form['receiver_address']
        req.delivery_date = request.form.get('delivery_date', '')
        req.sender_lat, req.sender_lon = geocode(req.sender_address)
        req.receiver_lat, req.receiver_lon = geocode(req.receiver_address)

        for item in req.items:
            db.session.delete(item)
        db.session.flush()

        cargo_names = request.form.getlist('cargo_name[]')
        quantities = request.form.getlist('quantity[]')
        weights = request.form.getlist('weight[]')
        lengths = request.form.getlist('length[]')
        widths = request.form.getlist('width[]')
        heights = request.form.getlist('height[]')
        product_ids = request.form.getlist('product_id[]')

        for i in range(len(cargo_names)):
            qty = int(quantities[i]) if quantities[i] else 1
            w = float(weights[i])
            l = float(lengths[i])
            wd = float(widths[i])
            h = float(heights[i])
            total_vol = l * wd * h * qty
            total_w = w * qty
            item = RequestItem(
                order_request_id=req.id,
                product_id=product_ids[i] if product_ids[i] else None,
                cargo_name=cargo_names[i],
                quantity=qty,
                length=l,
                width=wd,
                height=h,
                weight=w,
                total_volume=total_vol,
                total_weight=total_w
            )
            db.session.add(item)
        db.session.commit()
        return redirect(url_for('list_requests'))

    products = Product.query.order_by(Product.name).all()
    return render_template('request_form.html', request_obj=req, products=products)

@app.route('/request/<int:id>/delete', methods=['POST'])
def delete_request(id):
    req = OrderRequest.query.get_or_404(id)
    db.session.delete(req)
    db.session.commit()
    return redirect(url_for('list_requests'))

# ------------------ CRUD машин ------------------
@app.route('/vehicles')
def list_vehicles():
    vehicles = Vehicle.query.all()
    return render_template('vehicles.html', vehicles=vehicles)

@app.route('/vehicle/new', methods=['GET','POST'])
def new_vehicle():
    if request.method == 'POST':
        v = Vehicle(
            name=request.form['name'],
            plate=request.form['plate'],
            max_weight=float(request.form['max_weight']),
            length=float(request.form['length']),
            width=float(request.form['width']),
            height=float(request.form['height']),
            pallet_length=float(request.form.get('pallet_length', 1.2)),
            pallet_width=float(request.form.get('pallet_width', 0.8))
        )
        db.session.add(v)
        db.session.commit()
        return redirect(url_for('list_vehicles'))
    return render_template('vehicle_form.html', vehicle=None)

@app.route('/vehicle/<int:id>/edit', methods=['GET','POST'])
def edit_vehicle(id):
    v = Vehicle.query.get_or_404(id)
    if request.method == 'POST':
        v.name = request.form['name']
        v.plate = request.form['plate']
        v.max_weight = float(request.form['max_weight'])
        v.length = float(request.form['length'])
        v.width = float(request.form['width'])
        v.height = float(request.form['height'])
        v.pallet_length = float(request.form.get('pallet_length', 1.2))
        v.pallet_width = float(request.form.get('pallet_width', 0.8))
        db.session.commit()
        return redirect(url_for('list_vehicles'))
    return render_template('vehicle_form.html', vehicle=v)

@app.route('/vehicle/<int:id>/delete', methods=['POST'])
def delete_vehicle(id):
    v = Vehicle.query.get_or_404(id)
    db.session.delete(v)
    db.session.commit()
    return redirect(url_for('list_vehicles'))

# ------------------ Автопланирование ------------------
@app.route('/auto_plan', methods=['POST'])
def auto_plan():
    new_reqs = OrderRequest.query.filter_by(status='new').all()
    if not new_reqs:
        return redirect(url_for('index'))

    vehicles = Vehicle.query.filter_by(status='available').order_by(Vehicle.max_weight.desc()).all()

    for v in vehicles:
        total_w = 0
        total_v = 0
        for r in new_reqs:
            for item in r.items:
                total_w += item.total_weight
                total_v += item.total_volume

        if total_w <= v.max_weight and total_v <= (v.length * v.width * v.height):
            route = Route(vehicle_id=v.id)
            db.session.add(route)
            db.session.flush()

            for r in new_reqs:
                r.status = 'planned'
                r.route_id = route.id

            waypoints = []
            for r in new_reqs:
                if r.sender_lat and r.sender_lon:
                    waypoints.append((r.sender_lat, r.sender_lon, r.sender_address))
                if r.receiver_lat and r.receiver_lon:
                    waypoints.append((r.receiver_lat, r.receiver_lon, r.receiver_address))
            route.waypoints = json.dumps([{'lat': lat, 'lon': lon, 'desc': desc}
                                          for lat, lon, desc in waypoints])
            db.session.commit()

            if len(waypoints) >= 2:
                osrm_data = get_route_osrm([(lat, lon) for lat, lon, _ in waypoints])
                if osrm_data:
                    route.distance_km = round(osrm_data['routes'][0]['distance'] / 1000, 2)
                    route.duration_min = round(osrm_data['routes'][0]['duration'] / 60, 1)
                    route.route_geojson = json.dumps(osrm_data['routes'][0]['geometry'])

            positions = [(v.length * 100 / 2, total_w)]
            front, rear = axle_distribution(v.length * 100, positions, v.max_weight)
            route.axle_front = front
            route.axle_rear = rear

            v.status = 'in_route'
            db.session.commit()
            return redirect(url_for('view_route', route_id=route.id))

    return "Нет подходящей машины для всех заявок", 400

# ------------------ Просмотр рейса ------------------
@app.route('/route/<int:route_id>')
def view_route(route_id):
    route = Route.query.get_or_404(route_id)
    vehicle = Vehicle.query.get(route.vehicle_id)
    orders = OrderRequest.query.filter_by(route_id=route_id).all()

    # Все позиции и подсчёт паллет
    all_items = []
    item_pallets = []
    for o in orders:
        for item in o.items:
            np = pallets_needed(item, vehicle)
            item_pallets.append(np)
            all_items.append(item)

    # Группируем товары по адресу получателя
    from collections import defaultdict
    grouped = defaultdict(list)
    for o in orders:
        addr = o.receiver_address
        for item in o.items:
            grouped[addr].append({
                'name': item.cargo_name,
                'qty': item.quantity,
                'weight': item.total_weight,
                'pallets': pallets_needed(item, vehicle)
            })

    grouped_items = []
    for addr, items in grouped.items():
        grouped_items.append({'address': addr, 'cargo_items': items})

    return render_template('route_plan.html',
                           route=route,
                           vehicle=vehicle,
                           orders=orders,
                           all_items=all_items,
                           item_pallets=item_pallets,
                           waypoints=json.loads(route.waypoints or '[]'),
                           grouped_items=grouped_items,
                           yandex_key=app.config['YANDEX_MAPS_API_KEY'])

@app.route('/route/<int:route_id>/print_load')
def print_load(route_id):
    route = Route.query.get_or_404(route_id)
    vehicle = Vehicle.query.get(route.vehicle_id)
    orders = OrderRequest.query.filter_by(route_id=route_id).all()
    cargo = []
    for o in orders:
        for item in o.items:
            np = pallets_needed(item, vehicle)
            cargo.append({
                'name': item.cargo_name,
                'qty': item.quantity,
                'weight': item.total_weight,
                'pallets': np
            })
    if vehicle.pallet_width and vehicle.pallet_length:
        cols = int(vehicle.width // vehicle.pallet_width)
        rows = int(vehicle.length // vehicle.pallet_length)
    else:
        cols = rows = 0
    total_slots = cols * rows if cols and rows else 0
    placements = []
    current = 0
    for item in cargo:
        for _ in range(item['pallets']):
            if current < total_slots:
                row = current // cols
                col = current % cols
                placements.append({'name': item['name'], 'row': row, 'col': col})
                current += 1
            else:
                placements.append({'name': item['name'], 'row': -1, 'col': -1, 'error': True})
    return render_template('print_load.html',
                           route=route, vehicle=vehicle, cargo=cargo,
                           axle_front=route.axle_front, axle_rear=route.axle_rear,
                           placements=placements, cols=cols, rows=rows)

# ------------------ 3D схема загрузки ------------------
@app.route('/route/<int:route_id>/load_3d')
def load_3d(route_id):
    route = Route.query.get_or_404(route_id)
    vehicle = Vehicle.query.get(route.vehicle_id)
    orders = OrderRequest.query.filter_by(route_id=route_id).all()

    # Собираем все позиции с количеством
    all_items = []
    for o in orders:
        for item in o.items:
            all_items.append({
                'name': item.cargo_name,
                'qty': item.quantity,
                'length': item.length,
                'width': item.width,
                'height': item.height,
                'weight': item.weight
            })

    # Размеры паллеты и кузова (в метрах)
    pallet_l = vehicle.pallet_length or 1.2
    pallet_w = vehicle.pallet_width or 0.8
    max_pallet_h = vehicle.height

    truck_l = vehicle.length
    truck_w = vehicle.width
    truck_h = vehicle.height

    # Упаковка на паллеты
    try:
        pallets = packing.pack_items_to_pallets(all_items, pallet_l, pallet_w, max_pallet_h)
        # Размещение паллет в кузове
        placed_pallets = packing.pack_pallets_into_truck(pallets, truck_l, truck_w, truck_h)
    except Exception as e:
        return f"Ошибка упаковки: {e}", 500

    return render_template('load_3d.html',
                           route=route,
                           vehicle=vehicle,
                           placed_pallets=placed_pallets,
                           truck_size=(truck_l, truck_h, truck_w))

# ------------------ Инициализация ------------------
@app.cli.command('init-db')
def init_db():
    db.create_all()
    print("База создана")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)