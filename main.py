"""
.
.
.
.
.
.
.
.
.
.
.
.
.
.

"""
import json
import math
import os
import random
import socket
import sys
import threading
import time

import pygame

# ----------------------------------------------------------------settings
W, H = 800, 450     # virtual screen, scaled to fit any phone
PORT = 5555
FPS = 60
SEND_HZ = 30
WIN_SCORE = 5
SHIP_R = 16
SHIP_SPEED = 230.0
BULLET_SPEED = 460.0
BULLET_DAMAGE = 20
FIRE_COOLDOWN = 0.30
JOY_R = 60.0

BG = (8, 10, 24)
GRID = (20, 26, 52)
WHITE = (240, 240, 250)
DIM = (130, 140, 170)
CYAN = (0, 220, 255)
MAGENTA = (255, 60, 200)
GREEN = (60, 230, 120)
RED = (255, 80, 80)
PCOL = [CYAN, MAGENTA]


# ------------------------------------------------------------------network
class LineSock:
    """..."""
    
    def __init__(self, s):
        self.s = s
        self.buf = b""
        self.wl = threading.Lock()
        
    def send(self, obj):
        data = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
        with self.wl:
            self.s.sendall(data)
            
    def recv(self):
        while b"\n" not in self.buf:
            chunk = self.s.recv(4096)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
            if len(self.buf) > 100000:
                raise ConnectionError("bad data")
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode())
        
    def close(self):
        try:
            self.s.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass 
        try:
            self.s.close()
        except OSError:
            pass 
            
            
class Net:
    def __init__(self):
        self.ls = None
        self.srv = None
        self.connected = False
        self.error = ""
        self.inp = {"mx": 0.0, "my": 0.0, "f": 0}       # joiner's controls (host side)
        self.latest = None
        self.stop = False
        
    # ---- host
    def start_host(self, code):
        threading.Thread(target=self._host_run, args=(code,), daemon=True).start()
        
    def _host_run(self, code):
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("", PORT))
            srv.listen(1)
            srv.settimeout(0.5)
            self.srv = srv
        except OSError as e:
            self.error = "Cannot open port %d: %s" % (PORT, e)
            return 
        while not self.stop:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return 
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.settimeout(5)
            ls = LineSock(conn)
            try:
                hello = ls.recv()
                if str(hello.get("code")) != code:
                    ls.send({"ok": 0})
                    ls.close()
                    continue
                ls.send({"ok": 1})
                conn.settimeout(None)
            except Exception:
                ls.close()
                continue
            self.ls = ls
            self.connected = True
            self._read_loop(ls, "host")
            return
            
    # ---- joiner
    def start_join(self, ip, code):
        threading.Thread(target=self._join_run, args=(ip, code), daemon=True).start()
        
    def _join_run(self, ip, code):
        try:
            s = socket.create_connection((ip, PORT), timeout=6)
            s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            ls = LineSock(s)
            ls.send({"code": code})
            reply = ls.recv()
            if not reply.get("ok"):
                self.error = "Wrong room code"
                ls.close()
                return 
            s.settimeout(None)
        except Exception as e:
            self.error = "Could not connect (%s)" % e
            return
        self.ls = ls
        self.connected = True
        self._read_loop(ls, "client")
        
    # ---- shared
    def _read_loop(self, ls, role):
        try:
            while not self.stop:
                msg = ls.recv()
                if role == "host":
                    self.inp = msg
                else:
                    self.latest = msg
        except Exception:
            pass 
        self.connected = False
        if not self.stop and not self.error:
            self.error = "Connection lost"
            
    def send(self, obj):
        if self.ls and self.connected:
            try:
                self.ls.send(obj)
            except Exception:
                self.connected = False
                if not self.error:
                    self.error = "Connection lost"
                    
    def shutdown(self):
        self.stop = True
        if self.ls:
            self.ls.close()
        if self.srv:
            try:
                self.srv.close()
            except OSError:
                pass 
                
                
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))    # no packet is sent; works with no internet
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"
        
        
# ---------------------------------------------------------------simulation
class Sim:
    """..."""
    
    def __init__(self):
        self.reset_all()
        
    def reset_all(self):
        self.score = [0, 0]
        self.new_round()
        
    def new_round(self):
        self.pos = [[100.0, H / 2], [W - 100.0, H / 2]]
        self.ang = [0.0, math.pi]
        self.hp = [100, 100]
        self.cd = [0.0, 0.0]
        self.bul = []           # [x, y, vx, vy, owner]
        self.mode = "ready"
        self.timer = 1.2
        self.msg = "GET READY"
        
    def step(self, dt, inps):
        if self.mode in ("ready", "dead", "over"):
            self.timer -= dt
            if self.timer <= 0:
                if self.mode == "over":
                    self.reset_all()
                elif self.mode == "dead":
                    self.new_round()
                else:
                    self.mode = "play"
                    self.msg = ""
            return 
            
        for i in (0, 1):
            mx, my, fire = inps[i]
            mag = math.hypot(mx, my)
            if mag > 1:
                mx, my = mx / mag, my / mag
            p = self.pos[i]
            p[0] = min(W - SHIP_R, max(SHIP_R, p[0] + mx * SHIP_SPEED * dt))
            p[1] = min(H - SHIP_R, max(SHIP_R, p[1] + my * SHIP_SPEED * dt))
        for i in (0, 1):
            o = self.pos[1 - i]
            p = self.pos[i]
            self.ang[i] = math.atan2(o[1] - p[1], o[0] - p[0])
            self.cd[i] -= dt
            if inps[i][2] and self.cd[i] <= 0 and len(self.bul) < 60:
                a = self.ang[i]
                self.bul.append([p[0] + math.cos(a) * 20, p[1] + math.sin(a) * 20,
                                 math.cos(a) * BULLET_SPEED, math.sin(a) * BULLET_SPEED, i])
                self.cd[i] = FIRE_COOLDOWN
                
        alive = []
        for b in self.bul:
            b[0] += b[2] * dt
            b[1] += b[3] * dt
            if b[0] < -10 or b[0] > W + 10 or b[1] < -10 or b[1] > H + 10:
                continue
            tgt = 1 - b[4]
            if math.hypot(b[0] - self.pos[tgt][0], b[1] - self.pos[tgt][1]) < SHIP_R + 4:
                self.hp[tgt] -= BULLET_DAMAGE
                continue
            alive.append(b)
        self.bul = alive
        
        d0, d1 = self.hp[0] <= 0, self.hp[1] <= 0
        if d0 and d1:
            self.mode, self.timer, self.msg = "dead", 1.5, "DOUBLE KO!"
        elif d0 or d1:
            winner = 1 if d0 else 0
            self.score[winner] += 1
            if self.score[winner] >= WIN_SCORE:
                self.mode, self.timer = "over", 5.0
                self.msg = "PLAYER %d WINS!" % (winner + 1)
            else:
                self.mode, self.timer = "dead", 1.5
                self.msg = "PLAYER %d SCORES" % (winner + 1)
                
    def snapshot(self):
        return {
            "p": [[round(self.pos[i][0]), round(self.pos[i][1]), max(0, self.hp[i]),
                   self.score[i], round(self.ang[i], 2)] for i in (0, 1)],
            "bt": [[round(b[0]), round(b[1]), b[4]] for b in self.bul],
            "m": self.msg,
        }
        
        
# -----------------------------------------------------------------app
class App:
    def __init__(self):
        pygame.init()
        self.android = hasattr(sys, "getandroidapilevel") or "ANDROID_ARGUMENT" in os.environ
        if self.android:
            self.screen = pygame.display.set_mode((0, 0))
        else:
            self.screen = pygame.display.set_mode((W, H), pygame.RESIZABLE)
        pygame.display.set_caption("Cyber Duel")
        self.canvas = pygame.Surface((W, H))
        self.f_big = pygame.font.Font(None, 80)
        self.f_mid = pygame.font.Font(None, 42)
        self.f_sm = pygame.font.Font(None, 28)
        self.clock = pygame.time.Clock()
            
        self.state = "menu"    # menu, host_wait, join, joining, play
        self.net = None
        self.sim = None
        self.me = 0
        self.last_state = None
        self.code = ""
        self.ip_text = "192.168."
        self.code_text = ""
        self.field = "ip"
        self.msg = ""
        self.last_send = 0.0
        self.touches = {}    # id -> [x, y, start_x, start_y]
        self.saw_finger = False
        self.my_ip = get_local_ip()
        
    # ---- coordinates / events
    def to_virtual(self, px, py):
        sw, sh = self.screen.get_size()
        sc = min(sw / W, sh / H)
        return (px - (sw - W * sc) / 2) / sc, (py - (sh - H * sc) / 2) / sc
        
    def handle_events(self):
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                return False
            if e.type == pygame.FINGERDOWN:
                self.saw_finger = True
                sw, sh = self.screen.get_size()
                x, y = self.to_virtual(e.x * sw, e.y * sh)
                self.touches[e.finger_id] = [x, y, x, y]
                self.tap(x, y)
            elif e.type == pygame.FINGERMOTION:
                if e.finger_id in self.touches:
                    sw, sh = self.screen.get_size()
                    x, y = self.to_virtual(e.x * sw, e.y * sh)
                    self.touches[e.finger_id][0] = x
                    self.touches[e.finger_id][1] = y
            elif e.type == pygame.FINGERUP:
                self.touches.pop(e.finger_id, None)
            elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                if not getattr(e, "touch", False) and not self.saw_finger:
                    x, y = self.to_virtual(*e.pos)
                    self.touches["m"] = [x, y, x, y]
                    self.tap(x, y)
            elif e.type == pygame.MOUSEMOTION:
                if "m" in self.touches:
                    x, y = self.to_virtual(*e.pos)
                    self.touches["m"][0] = x
                    self.touches["m"][1] = y
            elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
                self.touches.pop("m", None)
            elif e.type == pygame.KEYDOWN:
                self.key(e)
        return True
        
    def key(self, e):
        if self.state != "join":
            return 
        if e.key == pygame.K_BACKSPACE:
            self.type_key("<")
        elif e.key == pygame.K_TAB:
            self.field = "code" if self.field == "ip" else "ip"
        elif e.key == pygame.K_RETURN:
            self.action("connect")
        elif e.unicode and e.unicode in "0123456789.":
            self.type_key(e.unicode)
            
    # ---- buttons per screen
    def buttons(self):
        R = pygame.Rect
        if self.state == "menu":
            return [(R(250, 170, 300, 70), "HOST GAME", "host"),
                    (R(250, 260, 300, 70), "JOIN GAME", "join")]
        if self.state in ("host_wait", "joining"):
            return [(R(300, 370, 200, 56), "CANCEL", "menu")]
        if self.state == "join":
            b = [(R(40, 70, 360, 54), "", "field_ip"),
                 (R(40, 150, 360, 54), "", "field_code"),
                 (R(40, 240, 170, 60), "CONNECT", "connect"),
                 (R(230, 240, 170, 60), "BACK", "menu")]
            keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "<"]
            for i, k in enumerate(keys):
                col, row = i % 3, i // 3
                b.append((R(440 + col * 110, 40 + row * 70, 100, 60), k, "k:" + k))
            return b
        return []
        
    def tap(self, x, y):
        for rect, _label, act in self.buttons():
            if rect.collidepoint(x, y):
                self.action(act)
                return 
                
    def close_net(self):
        if self.net:
            self.net.shutdown()
        self.net = None
        
    def action(self, act):
        if act == "host":
            self.close_net()
            self.code = "%04d" % random.randint(0, 9999)
            self.my_ip = get_local_ip()
            self.net = Net()
            self.net.start_host(self.code)
            self.last_state = None
            self.touches.clear()
            self.me = 0
            self.msg = ""
            self.state = "host_wait"
        elif act == "join":
            self.msg = ""
            self.state = "join"
        elif act == "menu":
            self.close_net()
            self.state = "menu"
        elif act == "field_ip":
            self.field = "ip"
        elif act == "field_code":
            self.field = "code"
        elif act == "connect":
            ip, code = self.ip_text.strip(), self.code_text.strip()
            if not ip or len(code) != 4:
                self.msg = "Enter the host IP and the 4-digit code"
                return 
            self.close_net()
            self.net = Net()
            self.net.start_join(ip, code)
            self.last_state = None
            self.touches.clear()
            self.me = 1
            self.msg = ""
            self.state = "joining"
        elif act.startswith("k:"):
            self.type_key(act[2:])
            
    def type_key(self, ch):
        if self.field == "ip":
            if ch == "<":
                self.ip_text = self.ip_text[:-1]
            elif len(self.ip_text) < 15:
                self.ip_text += ch
        else:
            if ch == "<":
                self.code_text = self.code_text[:-1]
            elif ch != "." and len(self.code_text) < 4:
                self.code_text += ch
                
    # ---- controls
    def get_input(self):
        mx = my = 0.0
        fire = 0
        for x, y, sx, sy in self.touches.values():
            if sx < W / 2:
                mx, my = (x - sx) / JOY_R, (y - sy) / JOY_R
            else:
                fire = 1
        keys = pygame.key.get_pressed()
        kx = (keys[pygame.K_d] or keys[pygame.K_RIGHT]) - (keys[pygame.K_a] or keys[pygame.K_LEFT])
        ky = (keys[pygame.K_s] or keys[pygame.K_DOWN]) - (keys[pygame.K_w] or keys[pygame.K_UP])
        if kx or ky:
            mx, my = float(kx), float(ky)
        if keys[pygame.K_SPACE]:
            fire = 1
        mag = math.hypot(mx, my)
        if mag > 1:
            mx, my = mx / mag, my / mag
        return mx, my, fire
        
    # ---- update
    def update(self, dt):
        if self.state == "host_wait":
            if self.net.error:
                self.msg = self.net.error 
                self.action("menu")
            elif self.net.connected:
                self.sim = Sim()
                self.last_state = self.sim.snapshot()
                self.state = "play"
        elif self.state == "joining":
            if self.net.error:
                self.msg = self.net.error 
                self.close_net()
                self.state = "join"
            elif self.net.connected:
                self.state = "play"
        elif self.state == "play":
            now = time.time()
            if not self.net.connected:
                self.msg = self.net.error or "Disconnected"
                self.action("menu")
                return 
            mx, my, fire = self.get_input()
            if self.me == 0:
                rem = self.net.inp
                try:
                    other = (float(rem.get("mx", 0)), float(rem.get("my", 0)), int(rem.get("f", 0)))
                except Exception:
                    other = (0.0, 0.0, 0)
                self.sim.step(dt, [(mx, my, fire), other])
                self.last_state = self.sim.snapshot()
                if now - self.last_send >= 1.0 / SEND_HZ:
                    self.net.send(self.last_state)
                    self.last_send = now
            else:
                if now - self.last_send >= 1.0 / SEND_HZ:
                    self.net.send({"mx": round(mx, 2), "my": round(my, 2), "f": fire})
                    self.last_send = now
                if self.net.latest is not None:
                    self.last_state = self.net.latest
                    
        # ---- drawing
    def text(self, s, font, color, center=None, topleft=None):
        img = font.render(s, True, color)
        r = img.get_rect()
        if center:
            r.center = center
        if topleft:
            r.topleft = topleft
        self.canvas.blit(img, r)
            
    def button(self, rect, label, color=(25, 50, 90)):
        pygame.draw.rect(self.canvas, color, rect, border_radius=10)
        pygame.draw.rect(self.canvas, CYAN, rect, 2, border_radius=10)
        if label:
            self.text(label, self.f_mid, WHITE, center=rect.center)
                
    def draw_ship(self, x, y, ang, color, is_me):
        pts = [(x + math.cos(ang) * 20, y + math.sin(ang) * 20),
               (x + math.cos(ang + 2.5) * 16, y + math.sin(ang + 2.5) * 16),
               (x + math.cos(ang - 2.5) * 16, y + math.sin(ang - 2.5) * 16)]
        pygame.draw.polygon(self.canvas, color, pts)
        pygame.draw.polygon(self.canvas, WHITE if is_me else BG, pts, 2)
            
    def draw_game(self):
        c = self.canvas 
        c.fill(BG)
        for gx in range(0, W + 1, 50):
            pygame.draw.line(c, GRID, (gx, 0), (gx, H))
        for gy in range(0, H + 1, 50):
            pygame.draw.line(c, GRID, (0, gy), (W, gy))
        pygame.draw.rect(c, CYAN, (0, 0, W, H), 3)
        st = self.last_state
        if st is None:
            self.text("Waiting for host...", self.f_mid, WHITE, center=(W // 2, H // 2))
            return 
        for bx, by, owner in st["bt"]:
            pygame.draw.circle(c, PCOL[owner], (bx, by), 5)
            pygame.draw.circle(c, WHITE, (bx, by), 2)
        for i, (x, y, hp, score, ang) in enumerate(st["p"]):
            self.draw_ship(x, y, ang, PCOL[i], i == self.me)
            if i == self.me:
                self.text("YOU", self.f_sm, WHITE, center=(x, y + 30))
        # health bars + score
        for i, (_x, _y, hp, score, _a) in enumerate(st["p"]):
            bx = 20 if i == 0 else W - 220
            pygame.draw.rect(c, (40, 40, 60), (bx, 16, 200, 14))
            pygame.draw.rect(c, GREEN if hp > 40 else RED, (bx, 16, 2 * hp, 14))
            pygame.draw.rect(c, PCOL[i], (bx, 16, 200, 14), 2)
        self.text("%d : %d" % (st["p"][0][3], st["p"][1][3]), self.f_mid, WHITE, center=(W // 2, 24))
        if st["m"]:
            self.text(st["m"], self.f_big, WHITE, center=(W // 2, H // 2 - 40))
        # touch hints
        pygame.draw.circle(c, DIM, (W - 90, H - 80), 50, 2)
        self.text("FIRE", self.f_sm, DIM, center=(W - 90, H - 80))
        for x, y, sx, sy in self.touches.values():
            if sx < W / 2:
                dx, dy = x - sx, y - sy
                m = math.hypot(dx, dy)
                if m > JOY_R:
                    dx, dy = dx / m * JOY_R, dy / m * JOY_R
                pygame.draw.circle(c, DIM, (int(sx), int(sy)), int(JOY_R), 2)
                pygame.draw.circle(c, CYAN, (int(sx + dx), int(sy + dy)), 22)
            else:
                pygame.draw.circle(c, CYAN, (W - 90, H - 80), 50, 4)
                
    def draw(self):
        c = self.canvas
        if self.state == "play":
            self.draw_game()
        else:
            c.fill(BG)
            if self.state == "menu":
                self.text("CYBER DUEL", self.f_big, CYAN, center=(W // 2, 90))
                self.text("1v1 arena - 2 phones", self.f_sm, DIM, center=(W // 2, 135))
                if self.msg:
                    self.text(self.msg, self.f_sm, RED, center=(W // 2, 360))
            elif self.state == "host_wait":
                self.text("HOSTING", self.f_big, CYAN, center=(W // 2, 70))
                self.text("YOUR IP:  %s" % self.my_ip, self.f_mid, WHITE, center=(W // 2, 160))
                self.text("Room code: %s" % self.code, self.f_big, MAGENTA, center=(W // 2, 230))
                self.text("Tell player 2 to JOIN with these. Waiting...", self.f_sm, DIM,
                          center=(W // 2, 300))
            elif self.state == "joining":
                self.text("Connecting...", self.f_big, CYAN, center=(W // 2, 200))
            elif self.state == "join":
                self.text("IP address", self.f_sm, DIM, topleft=(40, 44))
                self.text("Room code", self.f_sm, DIM, topleft=(40, 124))
            for rect, label, act in self.buttons():
                if act in ("field_ip", "field_code"):
                    active = (self.field == "ip") == (act == "field_ip")
                    pygame.draw.rect(c, (20, 30, 60), rect, border_radius=8)
                    pygame.draw.rect(c, MAGENTA if active else CYAN, rect, 3 if active else 1,
                                     border_radius=8)
                    val = self.ip_text if act == "field_ip" else self.code_text
                    self.text(val, self.f_mid, WHITE, center=rect.center)
                else:
                    self.button(rect, label)
            if self.state == "join" and self.msg:
                self.text(self.msg, self.f_sm, RED, topleft=(40, 330))
        sw, sh = self.screen.get_size()
        sc = min(sw / W, sh / H)
        size = (int(W * sc), int(H * sc))
        self.screen.fill((0, 0, 0))
        self.screen.blit(pygame.transform.scale(c, size), ((sw - size[0]) // 2, (sh - size[1]) // 2))
        pygame.display.flip()
        
    def run(self):
        running = True
        while running:
            dt = min(0.05, self.clock.tick(FPS) / 1000.0)
            running = self.handle_events()
            self.update(dt)
            self.draw()
        self.close_net()
        pygame.quit()
        
        
if __name__ == "__main__":
    App().run()
    
