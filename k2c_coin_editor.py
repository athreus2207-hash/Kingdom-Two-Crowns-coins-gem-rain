#!/usr/bin/env python3
"""
Kingdom Two Crowns - Coin Editor (save file: global-v35 / global-v3x)

Cara kerja:
  File save = JSON yang di-gzip. Skrip ini TIDAK menulis ulang seluruh JSON
  (itu mengubah presisi float dan format, dan bisa membuat game crash).
  Skrip hanya mengganti angka "Coins" pada WalletData milik Player 1/2
  langsung di teks aslinya, sehingga byte lain tetap persis sama.

Contoh pakai:
  python k2c_coin_editor.py global-v35 --list
  python k2c_coin_editor.py global-v35 --player 1 --coins 100
  python k2c_coin_editor.py global-v35 --player both --coins 50 --gems 3
  python k2c_coin_editor.py global-v35 --campaign 0 --player 1 --coins 40 --all-islands
  python k2c_coin_editor.py global-v35 --invulnerable on   # EKSPERIMEN: flag kebal pemain
  python k2c_coin_editor.py global-v35 --invulnerable off
  python k2c_coin_editor.py global-v35 --restore        # kembalikan dari backup

PENTING: tutup game dulu sebelum mengedit. Backup (.bak) dibuat otomatis.
"""
import argparse
import gzip
import json
import re
import shutil
import struct
import sys
import time
import zlib
from pathlib import Path

# Header gzip persis seperti file asli game (dibuat oleh .NET: mtime=0, OS=0x0a)
GZIP_HEADER = bytes.fromhex("1f8b0800000000000" + "00a")
UID_RE = re.compile(r'"uniqueID":"(Player [12])--(\d+)"')
DECODER = json.JSONDecoder()


# ---------------------------------------------------------------- gzip I/O
def read_save(path: Path) -> str:
    return gzip.decompress(path.read_bytes()).decode("utf-8")


def write_save(path: Path, text: str) -> None:
    data = text.encode("utf-8")
    co = zlib.compressobj(9, zlib.DEFLATED, -15)  # raw deflate
    body = co.compress(data) + co.flush()
    tail = struct.pack("<II", zlib.crc32(data) & 0xFFFFFFFF, len(data) & 0xFFFFFFFF)
    path.write_bytes(GZIP_HEADER + body + tail)


# ---------------------------------------------------------------- locate
def find_player_comps(text: str, ctype: str = "WalletData", root=None):
    """Kembalikan komponen ctype milik Player 1/2 sesuai urutan dokumen.
    Tiap item: dict(campaign, island, land, player, uid, start, end, data)
    start/end = posisi string literal 'data' (termasuk tanda kutip) di teks."""
    mark = '"type":"%s","data":' % ctype
    root = root or json.loads(text)  # hanya untuk membaca, TIDAK dipakai untuk menulis
    expected = []
    for ci, camp in enumerate(root["campaigns"]):
        for ii, isl in enumerate(camp["_islands"]):
            for ob in isl["objects"]:
                if re.fullmatch(r"Player [12]", ob["name"]):
                    for comp in ob["componentData2"]:
                        if comp["type"] == ctype:
                            expected.append((ci, ii, isl["land"], ob["name"], ob["uniqueID"], comp["data"]))
                            break

    found = []
    for m in UID_RE.finditer(text):
        pos = text.find(mark, m.end())
        if pos < 0:
            continue
        q = pos + len(mark)
        data, end = DECODER.raw_decode(text, q)
        found.append((m.group(0), q, end, data))

    if len(found) != len(expected):
        sys.exit(f"[!] Jumlah {ctype} tidak cocok ({len(found)} vs {len(expected)}). Format save tidak dikenali.")

    out = []
    for (raw_uid, s, e, data), (ci, ii, land, name, uid, pdata) in zip(found, expected):
        if data != pdata or raw_uid.split('"')[-2] != uid:
            sys.exit("[!] Urutan komponen tidak cocok dengan hasil parse. Batal demi keamanan.")
        out.append(dict(campaign=ci, island=ii, land=land, player=int(name[-1]),
                        uid=uid, start=s, end=e, data=data))
    return root, out


def get_invuln(data: str) -> bool:
    return '"invulnerable":true' in data


def set_invuln(data: str, on: bool) -> str:
    new, n = re.subn(r'"invulnerable":(true|false)', '"invulnerable":%s' % ("true" if on else "false"), data, count=1)
    if n != 1:
        sys.exit("[!] Field invulnerable tidak ditemukan.")
    return new


def get_val(data: str, field: str) -> int:
    m = re.search(r'"currency":\{[^}]*?"%s":(\d+)' % field, data)
    return int(m.group(1)) if m else 0


def set_val(data: str, field: str, value: int) -> str:
    new, n = re.subn(r'("currency":\{[^}]*?"%s":)\d+' % field, r"\g<1>%d" % value, data, count=1)
    if n != 1:
        sys.exit(f"[!] Field currency.{field} tidak ditemukan.")
    return new


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="Kingdom Two Crowns coin editor")
    ap.add_argument("save", type=Path, help="path file save (mis. global-v35)")
    ap.add_argument("--list", action="store_true", help="tampilkan semua wallet pemain")
    ap.add_argument("--restore", action="store_true", help="kembalikan dari backup .bak terbaru")
    ap.add_argument("--campaign", type=int, help="indeks campaign (default: campaign aktif)")
    ap.add_argument("--player", choices=["1", "2", "both"], default="1")
    ap.add_argument("--coins", type=int, help="jumlah koin baru")
    ap.add_argument("--gems", type=int, help="jumlah gems baru (opsional)")
    ap.add_argument("--invulnerable", choices=["on", "off"],
                    help="EKSPERIMEN: set flag invulnerable pada DamageableData pemain")
    ap.add_argument("--all-islands", action="store_true",
                    help="edit juga pulau lain di campaign itu (default: hanya pulau saat ini)")
    args = ap.parse_args()

    if args.restore:
        baks = sorted(args.save.parent.glob(args.save.name + ".*.bak"))
        if not baks:
            sys.exit("[!] Tidak ada backup.")
        shutil.copy2(baks[-1], args.save)
        print(f"[ok] Dikembalikan dari {baks[-1].name}")
        return

    text = read_save(args.save)
    root, wallets = find_player_comps(text, "WalletData")
    _, damage = find_player_comps(text, "DamageableData", root)
    cur = root["_currentCampaign"]

    if args.list or (args.coins is None and args.gems is None and args.invulnerable is None):
        print(f"Campaign aktif: {cur}")
        for w in wallets:
            camp = root["campaigns"][w["campaign"]]
            tag = " <- aktif" if w["campaign"] == cur and w["land"] == camp["currentLand"] else ""
            print(f"  campaign {w['campaign']} | land {w['land']} | Player {w['player']} | "
                  f"Coins={get_val(w['data'],'Coins')} Gems={get_val(w['data'],'Gems')} "
                  f"Kebal={'ya' if get_invuln(next(x['data'] for x in damage if x['uid']==w['uid'] and x['campaign']==w['campaign'] and x['island']==w['island'])) else 'tidak'}{tag}")
        return

    camp_idx = cur if args.campaign is None else args.campaign
    camp = root["campaigns"][camp_idx]
    players = {1, 2} if args.player == "both" else {int(args.player)}
    def pick(items):
        return [w for w in items
                if w["campaign"] == camp_idx and w["player"] in players
                and (args.all_islands or w["land"] == camp["currentLand"])]

    targets = pick(wallets)
    dtargets = pick(damage) if args.invulnerable is not None else []
    if not targets:
        sys.exit("[!] Tidak ada pemain yang cocok.")

    for v, n in ((args.coins, "coins"), (args.gems, "gems")):
        if v is not None and v < 0:
            sys.exit(f"[!] {n} tidak boleh negatif.")

    # backup
    bak = args.save.with_name(f"{args.save.name}.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(args.save, bak)
    print(f"[ok] Backup: {bak.name}")

    # kumpulkan semua edit: (start, end, literal_baru, pesan)
    edits = []
    if args.coins is not None or args.gems is not None:
        for w in targets:
            d = w["data"]
            if args.coins is not None:
                d = set_val(d, "Coins", args.coins)
            if args.gems is not None:
                d = set_val(d, "Gems", args.gems)
            edits.append((w["start"], w["end"], json.dumps(d, ensure_ascii=False),
                          f"campaign {w['campaign']} land {w['land']} Player {w['player']}: "
                          f"Coins {get_val(w['data'],'Coins')} -> {get_val(d,'Coins')}, "
                          f"Gems {get_val(w['data'],'Gems')} -> {get_val(d,'Gems')}"))
    for w in dtargets:
        on = args.invulnerable == "on"
        d = set_invuln(w["data"], on)
        edits.append((w["start"], w["end"], json.dumps(d, ensure_ascii=False),
                      f"campaign {w['campaign']} land {w['land']} Player {w['player']}: "
                      f"Kebal {get_invuln(w['data'])} -> {on}"))

    # terapkan dari belakang supaya posisi tidak bergeser
    new_text = text
    for start, end, literal, msg in sorted(edits, key=lambda e: e[0], reverse=True):
        new_text = new_text[:start] + literal + new_text[end:]
        print("[ok]", msg)

    json.loads(new_text)  # validasi: harus tetap JSON valid
    write_save(args.save, new_text)
    # verifikasi tulis-baca
    assert read_save(args.save) == new_text
    print("[ok] Selesai. Buka game dan muat save.")


if __name__ == "__main__":
    main()
