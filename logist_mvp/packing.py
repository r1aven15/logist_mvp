# packing.py
import itertools

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
    pallet_items = []
    for idx, pdata in enumerate(pallets_data):
        w_options = [1.2, 0.8]
        h = pdata['height']
        d_options = [0.8, 1.2]
        placed = False
        for w, d in zip(w_options, d_options):
            if w <= truck_l and h <= truck_h and d <= truck_w:
                pallet_items.append(Item(f'Pallet_{idx}', w, h, d))
                placed = True
                break
        if not placed:
            pallet_items.append(Item(f'Pallet_{idx}', 1.2, h, 0.8))
    truck_bin = Bin('Truck', truck_l, truck_h, truck_w)
    pack_bin(truck_bin, pallet_items)
    result = []
    for p_item in truck_bin.items:
        idx = int(p_item.name.split('_')[1])
        # Передаём только нужные данные, без вложенных объектов Item
        result.append({
            'pallet_index': idx,
            'position': p_item.pos,
            'size': (p_item.w, p_item.h, p_item.d)
        })
    return result