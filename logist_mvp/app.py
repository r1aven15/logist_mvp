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

# API Keys
OPENROUTE_API_KEY = 'eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6ImE3OGI3YmU5OTkwZTQzMzliOWU5NGJiZTBlMzNmNjc3IiwiaCI6Im11cm11cjY0In0='
YANDEX_GEOCODER_KEY = 'e60a6693-9447-4ce2-9bde-548cbbe0a23d'
YANDEX_MAP_KEY = 'fe837480-2945-4bd9-9cfb-b987101b2305'
OLLAMA_KEY = 'fdb2e393a19f4adca924f6a4a8d4bb3b.QT78Pv7JLQDC9SnpWEyxozuA'

app.config['YANDEX_MAPS_API_KEY'] = YANDEX_MAP_KEY

db.init_app(app)

# ------------------ AI Ассистент (стабильный) ------------------
def call_ai_rules(cmd):
    new = OrderRequest.query.filter_by(status='new').count()
    cars = Vehicle.query.filter_by(status='available').count()
    routes = Route.query.count()
    pending = OrderRequest.query.filter_by(status='pending').count()
    planned = OrderRequest.query.filter_by(status='planned').count()
    done = OrderRequest.query.filter_by(status='completed').count()
    
    c = cmd.lower().strip()
    
    if c in ['помощь', 'help', '?']:
        return "📋 Команды:\n• Статистика\n• Машины\n• Оптимизируй\n• Сброс\n• Рейсы"
    
    if 'статистика' in c or c == 'сколько':
        return f"📊 Заявок: {new} новых, {pending} ожидает, {planned} в работе, {done} выполнено\n🚚 Машин: {cars}\n📍 Рейсов: {routes}"
    
    if 'машин' in c:
        return f"🚚 Свободных машин: {cars}"
    
    if 'заявк' in c:
        return f"📦 Новых заявок: {new}"
    
    if 'оптимизируй' in c or 'спланируй' in c or 'авто' in c:
        if new > 0 and cars > 0:
            return f"✅ Запускаю автопланирование! ({new} заявок, {cars} машин)"
        elif new == 0:
            return "❌ Нет новых заявок для планирования"
        else:
            return "❌ Нет свободных машин"
    
    if 'сброс' in c:
        return "✅ Сбрасываю все заявки в статус 'new'..."
    
    if 'рейс' in c or 'маршрут' in c:
        return f"📍 Рейсов: {routes}. Перехожу к списку..."
    
    if 'done' in c or 'выполнен' in c:
        return f"✅ Выполнено заявок: {done}"
    
    return f"Не понял: '{cmd}'. Напишите 'Помощь' для списка команд."

def call_ai(cmd):
    """AI - пробуем Ollama, иначе правила (всегда работает)"""
    # Если нет ключа Ollama - сразу правила
    if not OLLAMA_KEY or 'localhost' in OLLAMA_KEY:
        return call_ai_rules(cmd)
    
    try:
        r = requests.post(
            'http://localhost:11434/api/chat',
            json={'model': 'llama3', 'messages': [{'role': 'user', 'content': f"Ответь кратко: {cmd}"}]},
            timeout=15
        )
        if r.status_code == 200:
            content = r.json().get('message', {}).get('content', '')
            if content and len(content) > 5:
                return content
    except:
        pass
    
    # Всегда fallback на правила
    return call_ai_rules(cmd)

@app.route('/api/ai', methods=['POST'])
def ai():
    cmd = (request.json or {}).get('command', '')
    if not cmd:
        return jsonify({'error': 'Укажите команду'}), 400
    
    resp = call_ai(cmd)
    c = cmd.lower()
    
    if 'оптимизируй' in c or 'спланируй' in c:
        return jsonify({'redirect': '/auto_plan', 'text': resp})
    if 'сброс' in c:
        return jsonify({'redirect': '/requests/reset_all', 'text': resp})
    if 'рейс' in c or 'маршрут' in c:
        return jsonify({'redirect': '/routes', 'text': resp})
    if 'машин' in c:
        return jsonify({'text': resp})
    
    return jsonify({'text': resp})

# ------------------ Умная маршрутизация ------------------
def haversine(lat1, lon1, lat2, lon2):
    """Расстояние между двумя точками в км"""
    R = 6371  # радиус Земли
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def optimize_route_nearest_neighbor(warehouse_lat, warehouse_lon, orders):
    """
    Оптимизация маршрута методом ближайшего соседа.
    Начинаем от склада, потом едем к ближайшей точке, и т.д.
    """
    if not orders:
        return []
    
    # Создаём список точек с адресами
    points = []
    for o in orders:
        if o.receiver_lat and o.receiver_lon:
            points.append({
                'order': o,
                'lat': o.receiver_lat,
                'lon': o.receiver_lon,
                'address': o.receiver_address
            })
    
    if not points:
        return []
    
    # Алгоритм ближайшего соседа
    optimized = []
    current_lat, current_lon = warehouse_lat, warehouse_lon
    
    while points:
        # Находим ближайшую точку
        nearest = None
        min_dist = float('inf')
        
        for p in points:
            dist = haversine(current_lat, current_lon, p['lat'], p['lon'])
            if dist < min_dist:
                min_dist = dist
                nearest = p
        
        if nearest:
            optimized.append(nearest)
            points.remove(nearest)
            current_lat, current_lon = nearest['lat'], nearest['lon']
    
    return optimized

def optimize_route_cluster_by_distance(warehouse_lat, warehouse_lon, orders):
    """
    Кластеризация + оптимизация: группируем заявки по районам,
    затем строим маршрут между кластерами.
    Сначала ближние районы, потом дальние.
    """
    if not orders:
        return []
    
    # Создаём список точек
    points = []
    for o in orders:
        if o.receiver_lat and o.receiver_lon:
            points.append({
                'order': o,
                'lat': o.receiver_lat,
                'lon': o.receiver_lon,
                'address': o.receiver_address
            })
    
    if not points:
        return []
    
    # Сортируем по расстоянию от склада
    points_sorted = sorted(points, key=lambda p: haversine(warehouse_lat, warehouse_lon, p['lat'], p['lon']))
    
    return points_sorted

@app.route('/requests/reset_all', methods=['POST'])
def reset_all_requests():
    """Сбросить все заявки в статус 'new' для перепланирования"""
    from models import OrderRequest, Route, Vehicle
    
    # Удаляем пустые маршруты
    for r in Route.query.all():
        orders = OrderRequest.query.filter_by(route_id=r.id).count()
        if orders == 0:
            db.session.delete(r)
    
    # Сбрасываем заявки
    requests = OrderRequest.query.all()
    for req in requests:
        req.status = 'new'
        req.route_id = None
    
    # Освобождаем машины
    vehicles = Vehicle.query.all()
    for v in vehicles:
        v.status = 'available'
    
    db.session.commit()
    
    return redirect(url_for('list_requests'))

@app.route('/api/smart_optimize', methods=['POST'])
def smart_optimize_route():
    """API для умной оптимизации маршрута"""
    new_reqs = OrderRequest.query.filter_by(status='new').all()
    if not new_reqs:
        return jsonify({'error': 'Нет новых заявок'})
    
    # Склад
    warehouse_lat = 56.0
    warehouse_lon = 92.9
    
    # Оптимизируем
    optimized = optimize_route_cluster_by_distance(warehouse_lat, warehouse_lon, new_reqs)
    
    return jsonify({
        'orders_count': len(optimized),
        'route': [{'address': o['address'], 'lat': o['lat'], 'lon': o['lon']} for o in optimized]
    })

# ------------------ AI Ассистент ------------------
from datetime import datetime, timedelta

def parse_ai_command(text):
    """
    Парсит команду на русском языке и возвращает ответ.
    """
    text = text.lower().strip()
    
    # === Статистика ===
    if any(word in text for word in ['сколько', 'статистика', 'покажи', 'дай']):
        if 'заяв' in text or 'заказ' in text:
            new_count = OrderRequest.query.filter_by(status='new').count()
            planned_count = OrderRequest.query.filter_by(status='planned').count()
            completed_count = OrderRequest.query.filter_by(status='completed').count()
            return {
                'text': f"📊 Статистика заявок:\n• Новых: {new_count}\n• В работе: {planned_count}\n• Выполнено: {completed_count}",
                'new': new_count, 'planned': planned_count, 'completed': completed_count
            }
        
        if 'машин' in text or 'транспорт' in text or 'vehicles' in text.lower():
            available = Vehicle.query.filter_by(status='available').count()
            in_route = Vehicle.query.filter_by(status='in_route').count()
            return {
                'text': f"🚚 Транспорт:\n• Доступно: {available}\n• В рейсе: {in_route}",
                'available': available, 'in_route': in_route
            }
        
        if ' район' in text or ' районов' in text:
            # Статистика по районам
            districts = {}
            for req in OrderRequest.query.filter_by(status='new').all():
                if req.receiver_address:
                    # Простой парсинг района
                    addr = req.receiver_address.lower()
                    for d in ['свердловский', 'кировский', 'ленинский', 'октябрьский', 'железнодорожный', 'центральный']:
                        if d in addr:
                            districts[d] = districts.get(d, 0) + 1
            if districts:
                text = "📍 Заявки по районам:\n" + "\n".join(f"• {k.title()}: {v}" for k, v in sorted(districts.items(), key=lambda x: -x[1]))
                return {'text': text, 'districts': districts}
            return {'text': 'Нет данных о районах'}
    
    # === Действия ===
    if any(word in text for word in ['оптимизируй', 'построй', 'спланируй', 'создай маршрут']):
        # Запускаем автопланирование
        return {'action': 'auto_plan', 'text': '✅ Запускаю автопланирование...'}
    
    if any(word in text for word in ['отмени', 'удали']):
        if 'маршрут' in text or 'рейс' in text:
            return {'action': 'cancel_last', 'text': 'Для отмены последнего рейса перейдите на страницу рейса и нажмите "Удалить"'}
    
    if any(word in text for word in ['помоги', 'help', 'помощь']):
        return {'text': '''🤖 Доступные команды:
• "Сколько заявок?" - статистика
• "Сколько машин?" - транспорт
• "Заявки по районам" - по районам
• "Оптимизируй маршрут" - автопланирование
• "Покажи рейсы" - список рейсов
• "Помощь" - эта справка'''}
    
    if 'покажи' in text and ('рейс' in text or 'маршру' in text):
        routes = Route.query.order_by(Route.id.desc()).limit(5).all()
        if routes:
            text = "🛣️ Последние рейсы:\n" + "\n".join(
                f"• Рейс #{r.id}: {r.distance_km or 0} км" + (f" ({r.duration_min} мин)" if r.duration_min else "")
                for r in routes
            )
            return {'text': text}  # Только текст, без данных
        return {'text': 'Нет рейсов'}
    
    # === Поговорка ===
    if 'шутка' in text or 'анекдот' in text:
        jokes = [
            "Почему грузовик не стал грустить? Потому что у него было много тоннажа! 🚚",
            "Логист - это человек, который знает, куда едет груз, даже если груз сам не знает.",
            "Водитель-дальнобойщик: 24 часа в сутки думает о грузе, а остальное - о машине.",
        ]
        import random
        return {'text': random.choice(jokes)}
    
    # Не поняли
    return {'text': 'Не понял команду. Напишите "Помощь" для списка команд.', 'error': True}

# ------------------ AI Ассистент (упрощённый, без внешнего API) ------------------
# AI работает на правилах - стабильно, без вылетов

def call_ai_simple(command):
    """Простой AI на правилах без внешних вызовов"""
    # Статистика
    new_cnt = OrderRequest.query.filter_by(status='new').count()
    planned_cnt = OrderRequest.query.filter_by(status='planned').count()
    done_cnt = OrderRequest.query.filter_by(status='completed').count()
    vehicles = Vehicle.query.filter_by(status='available').count()
    routes = Route.query.count()
    
    cmd = command.lower().strip()
    
    # Точное совпадение для надёжности
    if cmd in ['помощь', 'help', 'команды', '?', 'helpme']:
        return """📋 Доступные команды:
• "Статистика" - сколько заявок и машин
• "Машины" - свободные машины
• "Оптимизируй" - запустить автопланирование
• "Сброс" - сбросить заявки в new
• "Рейсы" - показать список рейсов
• "Помощь" - эта справка"""
    
    if 'статистика' in cmd or cmd == 'сколько':
        return f"""📊 Статистика:
📦 Новых заявок: {new_cnt}
🚛 В работе: {planned_cnt}
✅ Выполнено: {done_cnt}
🚚 Свободных машин: {vehicles}
📍 Всего рейсов: {routes}"""
    
    if 'машин' in cmd and 'свободн' in cmd or cmd == 'машины':
        return f"🚚 Свободных машин: {vehicles}"
    
    if 'оптимизируй' in cmd or 'спланируй' in cmd or cmd == 'оптимизация':
        if new_cnt > 0 and vehicles > 0:
            return f"✅ Запускаю автопланирование! Найдено: {new_cnt} заявок, {vehicles} машин."
        elif new_cnt == 0:
            return "❌ Нет новых заявок для планирования."
        else:
            return "❌ Нет свободных машин."
    
    if 'сброс' in cmd:
        return "✅ Сбрасываю все заявки в статус 'new'..."
    
    if 'рейс' in cmd or 'маршрут' in cmd:
        return f"📍 Всего рейсов: {routes}. Переход к списку..."
    
    if cmd == 'заявки':
        return f"📦 Новых заявок: {new_cnt}"
    
    return f"""❓ Команда не распознана: "{command}"
Напишите "Помощь" для списка команд."""

@app.route('/api/ai', methods=['POST', 'GET'])
def ai_assistant():
    """Упрощённый AI ассистент"""
    if request.method == 'GET':
        return jsonify({'error': 'Use POST method'})
    
    command = ''
    if request.is_json:
        command = request.json.get('command', '') or ''
    else:
        command = request.form.get('command', '') or ''
    
    if not command:
        return jsonify({'error': 'Команда не указана'}), 400
    
    response = call_ai_simple(command)
    cmd = command.lower().strip()
    
    # Редиректы
    if 'оптимизируй' in cmd or 'спланируй' in cmd:
        return jsonify({'redirect': '/auto_plan', 'text': response})
    
    if 'сброс' in cmd:
        return jsonify({'redirect': '/requests/reset_all', 'text': response})
    
    if 'рейс' in cmd or 'маршрут' in cmd:
        return jsonify({'redirect': '/routes', 'text': response})
    
    return jsonify({'text': response})

# ------------------ Геокодирование через Яндекс ------------------
def yandex_geocode(address):
    """Возвращает (широта, долгота) или (None, None) при ошибке."""
    key = YANDEX_GEOCODER_KEY
    if not key or not address:
        return None, None
    
    addr = address.strip()
    
    # Пробуем разные варианты с указанием города
    search_variants = [
        f"Красноярск, {addr}",           # Приоритет - Красноярск
        f"Красноярский край, {addr}",  # Красноярский край
        addr                          # Оригинал
    ]
    
    for search_addr in search_variants:
        try:
            url = "https://geocode-maps.yandex.ru/1.x/"
            params = {
                "apikey": key,
                "geocode": search_addr,
                "format": "json",
                "results": 3,
                "lang": "ru_RU"
            }
            resp = requests.get(url, params=params, timeout=5)
            data = resp.json()
            members = data['response']['GeoObjectCollection'].get('featureMember', [])
            if not members:
                continue
            
            # Ищем ближайший к Красноярску
            for member in members:
                geo = member.get('GeoObject', {})
                meta = geo.get('metaDataProperty', {}).get('GeocoderMetaData', {})
                text = meta.get('text', '')
                
                # Проверяем регион
                if 'красноярск' in text.lower():
                    pos = geo.get('point', {}).get('pos')
                    if pos:
                        lon, lat = map(float, pos.split())
                        return lat, lon
            
            # Если не нашли красноярский - берём первый с типом house/street
            first = members[0]
            geo = first.get('GeoObject', {})
            pos = geo.get('point', {}).get('pos')
            if pos:
                lon, lat = map(float, pos.split())
                return lat, lon
                
        except Exception as e:
            print(f"Ошибка геокодирования: {e}")
    
    return None, None

@app.route('/api/geocode', methods=['POST'])
def api_geocode():
    addr = request.json.get('address', '')
    lat, lon = yandex_geocode(addr)
    if lat:
        return jsonify({'lat': lat, 'lon': lon})
    return jsonify({'error': 'Не найдено'}), 404

# ------------------ Поиск товаров ------------------
@app.route('/api/search_product')
def search_product():
    q = request.args.get('q', '').lower()
    # Try UTF-8 first, fallback to latin-1
    try:
        q = q.encode('latin-1').decode('utf-8')
    except:
        pass
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
def get_route_yandex(waypoints):
    """Маршрут через Яндекс API"""
    if not waypoints or len(waypoints) < 2:
        return None
    
    if not YANDEX_MAP_KEY:
        return None
    
    # Формат для Яндекса: waypoints через ~
    points_str = '~'.join([f'{lon},{lat}' for lat, lon in waypoints])
    
    url = "https://routes.yandex.ru/long/routes"
    params = {
        'apikey': YANDEX_MAP_KEY,
        'rll': points_str,
        'type': 'truck'  # Грузовой
    }
    
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            routes = data.get('routes', [])
            if routes:
                # Получаем геометрию маршрута
                geom = routes[0].get('geometry', {})
                total_dist = routes[0].get('distance', {}).get('value', 0)
                total_time = routes[0].get('duration', {}).get('value', 0)
                return {
                    'routes': [{
                        'distance': total_dist,
                        'duration': total_time,
                        'geometry': geom
                    }]
                }
    except Exception as e:
        print(f"Yandex route error: {e}")
    
    return None

def get_route_osrm(waypoints):
    """Маршрут через OpenRouteService API"""
    if not waypoints or len(waypoints) < 2:
        return None
    
    # Сначала пробуем Яндекс
    route = get_route_yandex(waypoints)
    if route:
        return route
    
    # Fallback на OpenRouteService
    coords = [[lon, lat] for lat, lon in waypoints]
    coords_str = ';'.join([f'{c[0]},{c[1]}' for c in coords])
    
    url = f'https://api.openrouteservice.org/v2/directions/driving-car/geojson'
    headers = {'Authorization': OPENROUTE_API_KEY}
    
    try:
        resp = requests.get(url, params={'coordinates': coords_str}, headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('features'):
                geom = data['features'][0]['geometry']
                summary = data['features'][0]['properties']['summary']
                return {
                    'routes': [{
                        'distance': summary['distance'],
                        'duration': summary['duration'],
                        'geometry': geom
                    }]
                }
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
    district = request.args.get('district', '')
    date = request.args.get('date', '')
    status = request.args.get('status', '')
    
    query = OrderRequest.query
    
    if district:
        query = query.filter(OrderRequest.receiver_name.like(f'%{district}%'))
    if date:
        query = query.filter(OrderRequest.delivery_date == date)
    if status:
        query = query.filter(OrderRequest.status == status)
    
    all_req = query.order_by(OrderRequest.id.desc()).all()
    
    # Статистика
    stats = {}
    for d in ['Свердловский', 'Кировский', 'Ленинский', 'Октябрьский', 'Железнодорожный', 'Центральный']:
        stats[d] = OrderRequest.query.filter(
            OrderRequest.receiver_name.like(f'%{d}%'),
            OrderRequest.status == 'new'
        ).count()
    
    return render_template('requests.html', requests=all_req, stats=stats, 
                     current_district=district, current_date=date, current_status=status)

# Создать тестовые заявки
@app.route('/requests/generate', methods=['POST'])
def generate_requests():
    """Создать тестовые заявки для теста"""
    from models import OrderRequest, RequestItem, Product
    import random
    
    districts = {
        'Свердловский': (56.01, 92.87),
        'Кировский': (56.03, 92.91),
        'Ленинский': (55.99, 92.85),
        'Октябрьский': (56.02, 92.89),
        'Железнодорожный': (56.00, 92.83),
        'Центральный': (56.04, 92.86),
    }
    shops = [
        ('Магазин №1', 'ул. 9 Мая, 10'),
        ('Магазин №2', 'ул. Алексеева, 25'),
        ('Магазин №3', 'ул. Телевизорная, 1'),
        ('Магазин №4', 'ул. Мира, 50'),
        ('Магазин №5', 'пр. Красноярский рабочий, 100'),
        ('Магазин №6', 'ул. Партизана Железняка, 35'),
        ('Магазин №7', 'ул. Ленина, 15'),
        ('Магазин №8', 'ул. Маркса, 30'),
    ]
    products = Product.query.all()
    
    count = int(request.form.get('count', 10))
    
    for i in range(count):
        district_name, (lat, lon) = random.choice(list(districts.items()))
        shop = random.choice(shops)
        prod = random.choice(products)
        qty = random.randint(20, 80)
        
        order = OrderRequest(
            sender_name='Склад РОЗНИЦА',
            sender_address='Красноярск, ул. 60 лет Октября, 1',
            sender_lat=56.0,
            sender_lon=92.9,
            receiver_name=f'{shop[0]} ({district_name})',
            receiver_address=f'Красноярск, {shop[1]}',
            receiver_lat=lat + random.uniform(-0.005, 0.005),
            receiver_lon=lon + random.uniform(-0.005, 0.005),
            delivery_date=request.form.get('date', '2026-05-04'),
            status='new'
        )
        db.session.add(order)
        db.session.flush()
        
        item = RequestItem(
            order_request_id=order.id,
            cargo_name=prod.name,
            quantity=qty,
            length=prod.length,
            width=prod.width,
            height=prod.height,
            weight=prod.weight,
            total_volume=prod.length * prod.width * prod.height * qty,
            total_weight=prod.weight * qty
        )
        db.session.add(item)
    
    db.session.commit()
    return redirect(url_for('list_requests'))

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
        req.sender_lat, req.sender_lon = yandex_geocode(req.sender_address)
        req.receiver_lat, req.receiver_lon = yandex_geocode(req.receiver_address)
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
        req.sender_lat, req.sender_lon = yandex_geocode(req.sender_address)
        req.receiver_lat, req.receiver_lon = yandex_geocode(req.receiver_address)

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
    global optimize_route_nearest_neighbor, optimize_route_cluster_by_distance
    
    new_reqs = OrderRequest.query.filter_by(status='new').all()
    if not new_reqs:
        return redirect(url_for('index'))

    vehicles = Vehicle.query.filter_by(status='available').order_by(Vehicle.max_weight.desc()).all()

    # Склад
    warehouse_lat = 56.0
    warehouse_lon = 92.9

    for v in vehicles:
        total_w = 0
        total_v = 0
        for r in new_reqs:
            for item in r.items:
                total_w += item.total_weight
                total_v += item.total_volume

        # Если всё влезает - хорошо
        if total_w <= v.max_weight and total_v <= (v.length * v.width * v.height):
            route = Route(vehicle_id=v.id)
            db.session.add(route)
            db.session.flush()

            # Оптимизируем порядок заявок
            optimized = optimize_route_cluster_by_distance(warehouse_lat, warehouse_lon, new_reqs)
            
            for o in optimized:
                o['order'].status = 'planned'
                o['order'].route_id = route.id

            # waypoints: склад -> оптимизированный маршрут -> склад
            waypoints = [(warehouse_lat, warehouse_lon, 'Склад')]
            for o in optimized:
                waypoints.append((o['lat'], o['lon'], o['address']))
            waypoints.append((warehouse_lat, warehouse_lon, 'Склад'))
            
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

        # Иначе - загружаем сколько влезет (с оптимизацией)
        # Сначала оптимизируем все заявки
        optimized_all = optimize_route_cluster_by_distance(warehouse_lat, warehouse_lon, new_reqs)
        
        loaded = []
        w_sum, v_sum = 0, 0
        for o in optimized_all:
            r = o['order']
            rw = sum(i.total_weight for i in r.items)
            rv = sum(i.total_volume for i in r.items)
            if w_sum + rw <= v.max_weight and v_sum + rv <= (v.length * v.width * v.height):
                loaded.append(o)
                w_sum += rw
                v_sum += rv
        
        if loaded:
            route = Route(vehicle_id=v.id)
            db.session.add(route)
            db.session.flush()
            
            for o in loaded:
                o['order'].status = 'planned'
                o['order'].route_id = route.id
            
            # waypoints: склад -> оптимизированный маршрут -> склад
            waypoints = [(warehouse_lat, warehouse_lon, 'Склад')]
            for o in loaded:
                waypoints.append((o['lat'], o['lon'], o['address']))
            waypoints.append((warehouse_lat, warehouse_lon, 'Склад'))
            
            route.waypoints = json.dumps([{'lat': lat, 'lon': lon, 'desc': desc} for lat, lon, desc in waypoints])
            db.session.commit()

            if len(waypoints) >= 2:
                osrm_data = get_route_osrm([(lat, lon) for lat, lon, _ in waypoints])
                if osrm_data:
                    route.distance_km = round(osrm_data['routes'][0]['distance'] / 1000, 2)
                    route.duration_min = round(osrm_data['routes'][0]['duration'] / 60, 1)
                    route.route_geojson = json.dumps(osrm_data['routes'][0]['geometry'])

            positions = [(v.length * 100 / 2, w_sum)]
            front, rear = axle_distribution(v.length * 100, positions, v.max_weight)
            route.axle_front = front
            route.axle_rear = rear
            
            # Удаляем загруженные из new_reqs
            loaded_orders = [o['order'] for o in loaded]
            new_reqs = [r for r in new_reqs if r not in loaded_orders]
            
            v.status = 'in_route'
            db.session.commit()
            return redirect(url_for('view_route', route_id=route.id))
    
    return "Нет подходящей машины", 400

# ------------------ Просмотр рейса ------------------
@app.route('/route/<int:route_id>')
def view_route(route_id):
    route = Route.query.get_or_404(route_id)
    vehicle = db.session.get(Vehicle, route.vehicle_id)
    # Сортируем по ID (порядок добавления в маршрут)
    orders = OrderRequest.query.filter_by(route_id=route_id).order_by(OrderRequest.id).all()

    # Все позиции и подсчёт паллет - convert to dicts for JSON serialization
    all_items = []
    item_pallets = []
    for o in orders:
        for item in o.items:
            np = pallets_needed(item, vehicle)
            item_pallets.append(np)
            # Convert SQLAlchemy object to plain dict
            all_items.append({
                'cargo_name': item.cargo_name,
                'quantity': item.quantity,
                'total_weight': item.total_weight,
                'total_volume': item.total_volume
            })

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
    for idx, (addr, items) in enumerate(grouped.items()):
        grouped_items.append({'index': idx + 1, 'address': addr, 'cargo_items': items})

    return render_template('route_plan.html',
                           route=route,
                           vehicle=vehicle,
                           orders=orders,
                           all_items=all_items,
                           item_pallets=item_pallets,
                           waypoints=json.loads(route.waypoints or '[]'),
                           grouped_items=grouped_items,
                           yandex_key=app.config['YANDEX_MAPS_API_KEY'],
                           route_geojson=route.route_geojson)

@app.route('/route/<int:route_id>/print_load')
def print_load(route_id):
    route = Route.query.get_or_404(route_id)
    vehicle = db.session.get(Vehicle, route.vehicle_id)
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
    vehicle = db.session.get(Vehicle, route.vehicle_id)
    orders = OrderRequest.query.filter_by(route_id=route_id).order_by(OrderRequest.id.desc()).all()

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
                'weight': item.weight,
                'address': o.receiver_address  # Адрес для маркировки
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
    port = int(os.environ.get('PORT', 12000))
    app.run(host='0.0.0.0', port=port, debug=True)