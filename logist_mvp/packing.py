# packing.py

class Item:
    def __init__(self, name, w, h, d, weight=0.0):
        self.name = name
        self.w = float(w)
        self.h = float(h)
        self.d = float(d)
        self.weight = float(weight)
        self.pos = None  # (x,y,z)

    def volume(self):
        return self.w * self.h * self.d

class Bin:
    def __init__(self, name, w, h, d, max_weight=0.0):
        self.name = name
        self.w = float(w)
        self.h = float(h)
        self.d = float(d)
        self.max_weight = float(max_weight)
        self.items = []
        self.unfitted = []

def can_place(bin, item, pos):
    x, y, z = pos
    if x + item.w > bin.w or y + item.h > bin.h or z + item.d > bin.d:
        return False
    for placed in bin.items:
        px, py, pz = placed.pos
        pw, ph, pd = placed.w, placed.h, placed.d
        if (x < px + pw and x + item.w > px and
            y < py + ph and y + item.h > py and
            z < pz + pd and z + item.d > pz):
            return False
    return True

def find_spot(bin, item):
    spots = [(0, 0, 0)]
    for placed in bin.items:
        px, py, pz = placed.pos
        pw, ph, pd = placed.w, placed.h, placed.d
        spots += [
            (px + pw, py, pz),
            (px, py + ph, pz),
            (px, py, pz + pd)
        ]
    spots.sort(key=lambda s: s[0] + s[1] + s[2])
    for s in spots:
        if can_place(bin, item, s):
            return s
    return None

def pack_bin(bin, items):
    sorted_items = sorted(items, key=lambda x: x.volume(), reverse=True)
    for item in sorted_items:
        spot = find_spot(bin, item)
        if spot:
            item.pos = spot
            bin.items.append(item)
        else:
            bin.unfitted.append(item)

def pack_items_to_pallets(items, pallet_l, pallet_w, max_h):
    boxes = []
    for it in items:
        for _ in range(int(it['qty'])):
            boxes.append(Item(it['name'], it['length'], it['height'], it['width'], it.get('weight', 0)))
    pallets = []
    remaining = boxes[:]
    while remaining:
        pallet_bin = Bin('Pallet', pallet_l, max_h, pallet_w)
        pack_bin(pallet_bin, remaining)
        if not pallet_bin.items:
            break
        pallets.append(pallet_bin.items)
        remaining = pallet_bin.unfitted[:]
    result = []
    for pal in pallets:
        h = 0.0
        for item in pal:
            top = item.pos[1] + item.h
            if top > h:
                h = top
        # В результат кладём только высоту, без списка предметов (чтобы избежать несериализуемых объектов)
        result.append({'height': min(max_h, h)})
    return result

def pack_pallets_into_truck(pallets_data, truck_l, truck_w, truck_h):
    """
    Размещение паллет в обратном порядке маршрута:
    - Паллета для ПОСЛЕДНЕЙ точки маршрута (ближайшей к двери) - у двери (x = truck_l - PALLET_L)
    - Паллета для ПЕРВОЙ точки маршрута (ближайшей к кабине) - у кабины (x = 0)
    Так водитель разгружает сначала ближайшую точку, потом далее по порядку.
    """
    
    PALLET_L = 1.2
    PALLET_W = 0.8
    MARGIN = 0.3  # отступ от стен
    
    per_row = int(truck_l / PALLET_L)  # 5
    
    result = []
    
    for idx, pdata in enumerate(pallets_data):
        h = pdata['height']
        
        # Инвертируем порядок: последняя точка маршрута - первая паллета
        inv_idx = len(pallets_data) - 1 - idx
        row = inv_idx // per_row
        in_row = inv_idx % per_row
        
        # Z: у левой или правой стены с отступом
        z = MARGIN if row % 2 == 0 else truck_w - PALLET_W - MARGIN
        
        # x инвертирован: у двери ( truck_l - PALLET_L ) -> у кабины (0)
        x = (per_row - 1 - in_row) * PALLET_L
        
        if x + PALLET_L <= truck_l and z + PALLET_W <= truck_w and h <= truck_h:
            conflict = False
            for e in result:
                ex, ey, ez = e['position']
                ew, eh, ed = e['size']
                if (x < ex + ew and x + PALLET_L > ex and
                    z < ez + ed and z + PALLET_W > ez):
                    conflict = True
                    break
            
            if not conflict:
                result.append({
                    'pallet_index': idx,
                    'position': [x, 0, z],
                    'size': [PALLET_L, h, PALLET_W]
                })
                continue
        
        # Fallback
        z = MARGIN
        if x + PALLET_L <= truck_l and z + PALLET_W <= truck_w:
            result.append({
                'pallet_index': idx,
                'position': [x, 0, z],
                'size': [PALLET_L, h, PALLET_W]
            })
    
    return result