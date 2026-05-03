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
    Размещение паллет по 2 в ряд с учётом поворота:
    - Перебираем обе ориентации (1.2×0.8 и 0.8×1.2) для каждой паллеты
    - Выбираем лучшую с учётом уже размещённых
    - П1, П2 - у двери, П3, П4 - следующий ряд и т.д.
    """
    
    PALLET_L = 1.2
    PALLET_W = 0.8
    MARGIN = 0.1  # зазор между паллетами
    per_row = 2
    
    result = []
    placed = []  # уже размещённые паллеты для проверки перекрытия
    
    for idx, pdata in enumerate(pallets_data):
        h = pdata['height']
        
        # Пробуем обе ориентации
        best_pos = None
        best_size = None
        
        for rotate in [False, True]:
            if rotate:
                # Повёрнутая: 0.8 × 1.2
                p_l, p_w = PALLET_W, PALLET_L
            else:
                # Стандартная: 1.2 × 0.8
                p_l, p_w = PALLET_L, PALLET_W
            
            # Позиция в ряду
            row = idx // per_row
            in_row = idx % per_row
            
            # Z: чередование слева/справа
            z = MARGIN + in_row * p_w
            
            # X: от двери к кабине (задняя часть кузова - дверь)
            x = truck_l - MARGIN - (row + 1) * p_l
            
            # Проверяем что влезает
            if x >= 0 and z + p_w <= truck_w and h <= truck_h:
                # Проверяем перекрытие с уже размещёнными
                overlaps = False
                for prev in placed:
                    px, py, pz = prev['position']
                    pw, ph, pd = prev['size']
                    # Проверка перекрытия по X и Z
                    if (x < px + pw and x + p_l > px and
                        z < pz + pd and z + p_w > pz):
                        overlaps = True
                        break
                
                if not overlaps:
                    best_pos = [x, 0, z]
                    best_size = [p_l, h, p_w]
                    break  # нашли первое свободное место
        
        # Если не нашло - пробуем следующий свободный слот
        if best_pos is None:
            # Ищем любой свободный слот
            for row in range(20):  # до 20 рядов
                for in_row in range(per_row):
                    for rotate in [False, True]:
                        if rotate:
                            p_l, p_w = PALLET_W, PALLET_L
                        else:
                            p_l, p_w = PALLET_L, PALLET_W
                        
                        z = MARGIN + in_row * p_w
                        x = truck_l - MARGIN - (row + 1) * p_l
                        
                        if x >= 0 and z + p_w <= truck_w and h <= truck_h:
                            # Проверяем перекрытие
                            overlaps = False
                            for prev in placed:
                                px, py, pz = prev['position']
                                pw, ph, pd = prev['size']
                                if (x < px + pw and x + p_l > px and
                                    z < pz + pd and z + p_w > pz):
                                    overlaps = True
                                    break
                            
                            if not overlaps:
                                best_pos = [x, 0, z]
                                best_size = [p_l, h, p_w]
                                break
                    if best_pos:
                        break
                if best_pos:
                    break
        
        if best_pos is None:
            # Fallback - просто ставим где получится
            row = idx // per_row
            in_row = idx % per_row
            z = MARGIN + in_row * PALLET_W
            x = truck_l - MARGIN - (row + 1) * PALLET_L
            best_pos = [x, 0, z]
            best_size = [PALLET_L, h, PALLET_W]
        
        pallet_info = {
            'pallet_index': idx,
            'position': best_pos,
            'size': best_size,
            'address': pdata.get('address', ''),
            'items_count': pdata.get('items_count', 1)
        }
        result.append(pallet_info)
        placed.append(pallet_info)
    
    return result