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
    for idx, pal in enumerate(pallets):
        h = 0.0
        # Получаем адрес первого предмета на паллете
        address = ''
        for item in pal:
            if hasattr(item, 'name') and item.name:
                # Пробуем найти в original items
                for it in items:
                    if it.get('name') == item.name:
                        address = it.get('address', '')
                        break
                break
            top = item.pos[1] + item.h
            if top > h:
                h = top
        result.append({'height': min(max_h, h), 'address': address, 'items_count': len(pal)})
    return result

def pack_pallets_into_truck(pallets_data, truck_l, truck_w, truck_h):
    """
    Размещение паллет по 2 в ряд, от двери к кабине:
    - П1, П2 - у двери (сзади)
    - П3, П4 - следующий ряд
    - и т.д.
    """
    
    PALLET_L = 1.2
    PALLET_W = 0.8
    MARGIN = 0.3
    
    # 2 паллеты в ряд по длине
    per_row = 2
    result = []
    
    for idx, pdata in enumerate(pallets_data):
        h = pdata['height']
        
        # П1, П2 у двери (x = truck_l), П3, П4 ближе к кабине (x = truck_l - 2*PALLET_L)
        row = idx // per_row
        in_row = idx % per_row
        
        # Z: чередование слева/справа
        z = MARGIN + in_row * PALLET_W
        
        # X: от двери к кабине
        x = truck_l - MARGIN - (row + 1) * PALLET_L
        
        if x >= 0 and z + PALLET_W <= truck_w and h <= truck_h:
            result.append({
                'pallet_index': idx,
                'position': [x, 0, z],
                'size': [PALLET_L, h, PALLET_W],
                'address': pdata.get('address', ''),
                'items_count': pdata.get('items_count', 1)
            })
        else:
            # Fallback - простая укладка
            z = MARGIN + (idx % 2) * PALLET_W
            x = truck_l - MARGIN - ((idx // 2) + 1) * PALLET_L
            result.append({
                'pallet_index': idx,
                'position': [x, 0, z],
                'size': [PALLET_L, h, PALLET_W],
                'address': pdata.get('address', ''),
                'items_count': pdata.get('items_count', 1)
            })
    
    return result