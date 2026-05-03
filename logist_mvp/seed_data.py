import sys
from app import app, db
from models import Product, Vehicle, OrderRequest, RequestItem
import requests

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

def seed_products():
    products = [
        ("РОЛЛТОН Картофельное пюре 240г*10 пакет", 2.4, 0.3, 0.2, 0.25),
        ("РОЛЛТОН Лапша б/п (сыр с беконом) на домашнем бульоне 60г*42", 2.52, 0.35, 0.25, 0.3),
        ("Сайра 250г*24 д/м (К 026)", 6.0, 0.4, 0.3, 0.2),
        ("Салат из морской капусты 220г*24 (Доброфлот)", 5.28, 0.4, 0.3, 0.2),
        ("Сельдь 245г*24 с добавлением масла ЛВК (В 361)", 5.88, 0.4, 0.3, 0.2),
        ("Скумбрия с д/м 245г*24 (ЛВК) (В 750)", 5.88, 0.4, 0.3, 0.2),
        ("Суп ДАСМАР Гороховый по-Минусински 500г*8 ст/6", 4.0, 0.35, 0.3, 0.25),
        ("Суп ДАСМАР Свекольник по-Минусински 500г*8 ст/6", 4.0, 0.35, 0.3, 0.25),
        ("Шампань 'Прошу к столу' резан. 425мл*24 ж/б", 10.2, 0.4, 0.3, 0.25),
        ("Шампань 'Прошу к столу' резан. 850мл*12 ж/б", 10.2, 0.4, 0.3, 0.3),
        ("Шампань ЕКОЛАНД резан. 425мл*24 ж/б", 10.2, 0.4, 0.3, 0.25),
        ("Шампань ЕКОЛАНД резан. 850мл*12 ж/б", 10.2, 0.4, 0.3, 0.3),
        ("Сахар-рафинад 'РУССКИЙ' упак.", 5.0, 0.3, 0.2, 0.25),
        ("Сгущенка СГУСТЕНА ВАРЕНАЯ 380г*15", 5.7, 0.35, 0.3, 0.2),
        ("Соль 'Сибирская' 1кг*12", 12.0, 0.4, 0.3, 0.2),
        ("Соус жгучий чили 'МИВИМЕКС' 200г*15", 3.0, 0.3, 0.25, 0.2),
        ("Соус соевый МИВИМЕКС 200г*30", 6.0, 0.3, 0.25, 0.25),
        ("Спички 1*10*900 шт.", 2.0, 0.3, 0.2, 0.15),
        ("Сухарики 'КИРИЕШКИ' 60г+25мл/30", 2.55, 0.3, 0.25, 0.2),
        ("Томат. паста 'ДАСМАР' 1л*6", 6.0, 0.4, 0.3, 0.2),
        ("Томат. паста 'ДЯДЯ ВАНЯ' 25% 70гр*24", 1.68, 0.3, 0.2, 0.15),
        ("Тунец филе натур. 'ВКУСНЫЕ КОНСЕРВЫ' 185г*24", 4.44, 0.4, 0.3, 0.2),
        ("Уксус столовый 9% 1000мл*9", 9.0, 0.4, 0.3, 0.3),
        ("Фасоль 'ДЯДЯ ВАНЯ' 400гр*12 белая ж/б", 4.8, 0.4, 0.3, 0.2),
        ("Чипсы Бингре 'ЗЯКИ-ЗЯКИ' 50г*24", 1.2, 0.35, 0.25, 0.2),
        ("Горчица ДАСМАР 100*15 тюбик", 1.5, 0.25, 0.2, 0.15),
        ("Кисель Брусника с кусочками 6/10 30*4шт", 1.2, 0.3, 0.2, 0.15),
        ("Крупа 'Прозала' перловая 800*10", 8.0, 0.4, 0.3, 0.25),
        ("Майонез 'АВЕНИК ВУКА' 800г*6 д/м", 4.8, 0.35, 0.3, 0.2),
        ("Мука 'АЛЕЙКА' в/с 2кг*6 пшеничная", 12.0, 0.4, 0.3, 0.25),
        ("Напиток кофейный ТОРАВИКА CREAMY LATTE 30гр*20шт*12 бл.", 7.2, 0.4, 0.3, 0.3),
        ("РОЛЛТОН Картофельное пюре (курица) 40г*24", 0.96, 0.3, 0.2, 0.2),
        ("Суп ДАСМАР Рассольник по-Минусински 500г*8 ст/6", 4.0, 0.35, 0.3, 0.25),
        ("Ассорти овощ. 'ДЯДЬЯ ВАНЯ' марин. 1800гр*6 ст/6", 10.8, 0.4, 0.3, 0.3),
        ("Крупа 'АЛЕЙКА' Манная 1000г*8", 8.0, 0.4, 0.3, 0.2),
        ("Крупа 'АЛЕЙКА' Горох колотый 900г*15", 13.5, 0.4, 0.3, 0.25),
        ("БИГ БОН лапша Т/Ч 85г*24", 2.04, 0.3, 0.2, 0.25),
        ("БИГ БОН чипсы 140г*16", 2.24, 0.3, 0.25, 0.2),
        ("Бульон-приправа 'РОЛЛТОН' 100г*24", 2.4, 0.3, 0.2, 0.15),
        ("Говядина туш. 'БИЙСК' В/С 338г*24 ж/б", 8.11, 0.4, 0.3, 0.2),
        ("Икра кабачковая 'ДЯДЯ ВАНЯ' 460гр*8 ст/б", 3.68, 0.3, 0.25, 0.25),
        ("Кофе 'AMBASSADOR' растворимый 75г*12", 0.9, 0.2, 0.2, 0.2),
    ]

    for name, weight, l, w, h in products:
        p = Product(name=name, weight=weight, length=l, width=w, height=h, package_type="упак.")
        db.session.add(p)

    print(f"Добавлено товаров: {len(products)}")

def seed_vehicles():
    vehicles = [
        ("Isuzu Elf 3.5", "А111ВВ124", 3500, 4.0, 2.0, 2.0, 1.2, 0.8),
        ("Scania P280", "В222ЕЕ124", 5000, 5.5, 2.4, 2.2, 1.2, 0.8),
        ("Isuzu Forward", "С333ММ124", 5000, 6.0, 2.4, 2.3, 1.2, 1.0),
        ("Scania G360", "Т555ОО124", 7000, 7.0, 2.4, 2.4, 1.2, 1.0),
        ("Газель Next", "У777КУ124", 2000, 3.0, 2.0, 1.8, 1.2, 0.8),
    ]
    for name, plate, max_w, l, w, h, pl, pw in vehicles:
        v = Vehicle(name=name, plate=plate, max_weight=max_w, length=l, width=w, height=h,
                    pallet_length=pl, pallet_width=pw, status="available")
        db.session.add(v)
    print(f"Добавлено машин: {len(vehicles)}")

def seed_requests():
    requests_data = [
        ("Склад РОЗНИЦА", "Красноярск, ул. Телевизорная, 1",
         "Магазин Продукты", "Красноярск, ул. 9 Мая, 10",
         "РОЛЛТОН Картофельное пюре 240г*10 пакет", 5, 0.3, 0.2, 0.25, 2.4, "2026-05-10"),
        ("Склад РОЗНИЦА", "Красноярск, ул. Телевизорная, 1",
         "Магазин У дома", "Красноярск, ул. Алексеева, 25",
         "Сайра 250г*24 д/м (К 026)", 3, 0.4, 0.3, 0.2, 6.0, "2026-05-10"),
    ]

    for s_name, s_addr, r_name, r_addr, cargo, qty, l, w, h, weight, date in requests_data:
        lat_s, lon_s = geocode(s_addr)
        lat_r, lon_r = geocode(r_addr)
        order = OrderRequest(
            sender_name=s_name, sender_address=s_addr, sender_lat=lat_s, sender_lon=lon_s,
            receiver_name=r_name, receiver_address=r_addr, receiver_lat=lat_r, receiver_lon=lon_r,
            delivery_date=date, status="new"
        )
        db.session.add(order)
        db.session.flush()
        item = RequestItem(
            order_request_id=order.id,
            cargo_name=cargo,
            quantity=qty,
            length=l, width=w, height=h, weight=weight,
            total_volume=l * w * h * qty,
            total_weight=weight * qty
        )
        db.session.add(item)
    db.session.commit()
    print("Добавлено 2 тестовые заявки с позициями")

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        try:
            RequestItem.query.delete()
            OrderRequest.query.delete()
            Route.query.delete()
            Vehicle.query.delete()
            Product.query.delete()
            db.session.commit()
        except:
            db.session.rollback()
        seed_products()
        seed_vehicles()
        seed_requests()
        print("Готово! База заполнена.")