from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article = db.Column(db.String(50), default='')
    name = db.Column(db.String(200), nullable=False)
    weight = db.Column(db.Float, default=0.0)
    length = db.Column(db.Float, default=0.0)
    width = db.Column(db.Float, default=0.0)
    height = db.Column(db.Float, default=0.0)
    package_type = db.Column(db.String(50), default='упак.')

class OrderRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_name = db.Column(db.String(100))
    sender_address = db.Column(db.String(255))
    sender_lat = db.Column(db.Float)
    sender_lon = db.Column(db.Float)
    receiver_name = db.Column(db.String(100))
    receiver_address = db.Column(db.String(255))
    receiver_lat = db.Column(db.Float)
    receiver_lon = db.Column(db.Float)
    delivery_date = db.Column(db.String(20))
    status = db.Column(db.String(20), default='new')
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'), nullable=True)
    items = db.relationship('RequestItem', backref='order', lazy=True)

class RequestItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_request_id = db.Column(db.Integer, db.ForeignKey('order_request.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)
    cargo_name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    length = db.Column(db.Float)
    width = db.Column(db.Float)
    height = db.Column(db.Float)
    weight = db.Column(db.Float)
    total_volume = db.Column(db.Float)
    total_weight = db.Column(db.Float)

class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    plate = db.Column(db.String(20))
    max_weight = db.Column(db.Float)
    length = db.Column(db.Float)
    width = db.Column(db.Float)
    height = db.Column(db.Float)
    pallet_length = db.Column(db.Float, default=1.2)
    pallet_width = db.Column(db.Float, default=0.8)
    status = db.Column(db.String(20), default='available')

class Route(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey('vehicle.id'))
    created = db.Column(db.DateTime, default=datetime.utcnow)
    distance_km = db.Column(db.Float)
    duration_min = db.Column(db.Float)
    waypoints = db.Column(db.Text)
    route_geojson = db.Column(db.Text)
    axle_front = db.Column(db.Float)
    axle_rear = db.Column(db.Float)
class LoadPlan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    route_id = db.Column(db.Integer, db.ForeignKey('route.id'))
    data_json = db.Column(db.Text)  # JSON с результатами упаковки
    created = db.Column(db.DateTime, default=datetime.utcnow)