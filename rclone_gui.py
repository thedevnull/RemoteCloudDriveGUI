#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Rclone Mount Setup (GUI)
Detecta a distro, instala rclone + FUSE, cria/configura o remote e instala
um serviço systemd (user) que monta o remote em uma pasta.
"""
import os
import re
import shlex
import shutil
import subprocess
import threading
import queue
import getpass
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

SERVICE = "rclone-mount"
UNIT_DIR = Path.home() / ".config" / "systemd" / "user"
REMOTE_TYPES = ["drive", "onedrive", "dropbox", "box", "mega"]


# ----------------------------------------------------------------- helpers --
def have(cmd):
    return shutil.which(cmd) is not None


def clean_env():
    """Remove variáveis que o AppImage/Python empacotado possam ter definido."""
    env = dict(os.environ)
    for k in ("PYTHONHOME", "PYTHONPATH", "LD_LIBRARY_PATH", "LD_PRELOAD",
              "APPDIR", "APPIMAGE", "ARGV0", "OWD"):
        env.pop(k, None)
    return env


def distro_info():
    data = {}
    for p in ("/etc/os-release", "/usr/lib/os-release"):
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        data[k] = v.strip('"')
            break
    name = data.get("PRETTY_NAME") or data.get("NAME") or "Linux (desconhecida)"
    return name, data.get("ID", ""), data.get("ID_LIKE", "")


def package_commands():
    """Retorna (gerenciador, [comandos]) para instalar rclone + fuse3."""
    if have("pacman"):
        return "pacman", [["pacman", "-S", "--needed", "--noconfirm", "rclone", "fuse3"]]
    if have("apt-get"):
        return "apt", [["apt-get", "update"],
                       ["apt-get", "install", "-y", "rclone", "fuse3"]]
    if have("dnf"):
        return "dnf", [["dnf", "install", "-y", "rclone", "fuse3"]]
    if have("zypper"):
        return "zypper", [["zypper", "--non-interactive", "install", "rclone", "fuse3"]]
    if have("apk"):
        return "apk", [["apk", "add", "rclone", "fuse3"]]
    if have("xbps-install"):
        return "xbps", [["xbps-install", "-Sy", "rclone", "fuse3"]]
    return None, None


def fusermount_bin():
    return shutil.which("fusermount3") or shutil.which("fusermount")


def find_terminal(cmd):
    """Monta o comando para abrir `cmd` (lista) em um emulador de terminal."""
    joined = shlex.join(cmd)
    options = [
        ("x-terminal-emulator", ["-e"] + cmd),
        ("gnome-terminal", ["--"] + cmd),
        ("kgx", ["--"] + cmd),
        ("konsole", ["-e"] + cmd),
        ("xfce4-terminal", ["-e", joined]),
        ("mate-terminal", ["-e", joined]),
        ("kitty", cmd),
        ("alacritty", ["-e"] + cmd),
        ("xterm", ["-e"] + cmd),
    ]
    for term, args in options:
        if have(term):
            return [term] + args
    return None


# --------------------------------------------------------------------- GUI --
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Rclone Mount Setup")
        self.geometry("760x640")
        self.minsize(680, 560)

        self.q = queue.Queue()
        self.busy = False
        self.buttons = []

        self.distro_name, self.distro_id, self.distro_like = distro_info()
        self.pm, _ = package_commands()

        self.remote_var = tk.StringVar()
        self.type_var = tk.StringVar(value="drive")
        self.mount_var = tk.StringVar(value=str(Path.home() / "GoogleDrive"))
        self.linger_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.refresh_remotes()
        self.refresh_status_labels()
        self.after(100, self._poll)

        if os.geteuid() == 0:
            messagebox.showerror("Erro", "Não execute como root. O serviço é "
                                 "instalado para o usuário atual.")
            self.destroy()

    # ---------------------------------------------------------- UI builders --
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}
        root = ttk.Frame(self)
        root.pack(fill="both", expand=True)

        # Sistema
        f0 = ttk.LabelFrame(root, text="Sistema")
        f0.pack(fill="x", **pad)
        self.lbl_distro = ttk.Label(f0, text="")
        self.lbl_distro.pack(anchor="w", padx=8, pady=2)
        self.lbl_deps = ttk.Label(f0, text="")
        self.lbl_deps.pack(anchor="w", padx=8, pady=2)

        # Passo 1
        f1 = ttk.LabelFrame(root, text="1. Dependências (rclone + FUSE)")
        f1.pack(fill="x", **pad)
        b = ttk.Button(f1, text="Instalar dependências", command=self.on_install)
        b.pack(side="left", padx=8, pady=8)
        self.buttons.append(b)

        # Passo 2
        f2 = ttk.LabelFrame(root, text="2. Remote (nuvem)")
        f2.pack(fill="x", **pad)
        row = ttk.Frame(f2)
        row.pack(fill="x", padx=8, pady=6)
        ttk.Label(row, text="Nome:").pack(side="left")
        self.cb_remote = ttk.Combobox(row, textvariable=self.remote_var, width=22)
        self.cb_remote.pack(side="left", padx=6)
        ttk.Label(row, text="Tipo (novo):").pack(side="left", padx=(10, 0))
        ttk.Combobox(row, textvariable=self.type_var, values=REMOTE_TYPES,
                     width=12).pack(side="left", padx=6)
        row2 = ttk.Frame(f2)
        row2.pack(fill="x", padx=8, pady=(0, 8))
        for text, cmd in (("Criar remote (abre o navegador)", self.on_create_remote),
                          ("rclone config (terminal)", self.on_config_terminal),
                          ("Atualizar lista", self.refresh_remotes)):
            b = ttk.Button(row2, text=text, command=cmd)
            b.pack(side="left", padx=(0, 6))
            self.buttons.append(b)

        # Passo 3
        f3 = ttk.LabelFrame(root, text="3. Montagem automática (systemd)")
        f3.pack(fill="x", **pad)
        row = ttk.Frame(f3)
        row.pack(fill="x", padx=8, pady=6)
        ttk.Label(row, text="Pasta:").pack(side="left")
        ttk.Entry(row, textvariable=self.mount_var).pack(side="left", fill="x",
                                                         expand=True, padx=6)
        ttk.Button(row, text="Escolher…", command=self.on_browse).pack(side="left")
        ttk.Checkbutton(f3, text="Montar no boot, mesmo sem login (linger)",
                        variable=self.linger_var).pack(anchor="w", padx=8)
        row3 = ttk.Frame(f3)
        row3.pack(fill="x", padx=8, pady=8)
        for text, cmd in (("Criar serviço e montar", self.on_service),
                          ("Ver status", self.on_status),
                          ("Parar e remover serviço", self.on_remove)):
            b = ttk.Button(row3, text=text, command=cmd)
            b.pack(side="left", padx=(0, 6))
            self.buttons.append(b)

        # Log
        f4 = ttk.LabelFrame(root, text="Log")
        f4.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(f4, height=10, wrap="word", state="disabled",
                           font=("monospace", 9))
        sb = ttk.Scrollbar(f4, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

        self.progress = ttk.Progressbar(root, mode="indeterminate")
        self.progress.pack(fill="x", padx=10, pady=(0, 8))

    def refresh_status_labels(self):
        self.lbl_distro.config(
            text=f"Distro: {self.distro_name}   |   Gerenciador de pacotes: "
                 f"{self.pm or 'não reconhecido (usará instalador oficial)'}")
        r = "✔ instalado" if have("rclone") else "✘ ausente"
        fu = "✔ instalado" if fusermount_bin() else "✘ ausente"
        sd = "✔" if have("systemctl") else "✘ (systemd não encontrado!)"
        self.lbl_deps.config(text=f"rclone: {r}   |   FUSE: {fu}   |   systemd: {sd}")

    # ------------------------------------------------------------ log/queue --
    def write(self, text):
        self.q.put(("log", text))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self.log.config(state="normal")
                    self.log.insert("end", payload if payload.endswith("\n")
                                    else payload + "\n")
                    self.log.see("end")
                    self.log.config(state="disabled")
                elif kind == "done":
                    self._set_busy(False)
                    self.refresh_status_labels()
                    self.refresh_remotes()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _set_busy(self, busy):
        self.busy = busy
        for b in self.buttons:
            b.config(state="disabled" if busy else "normal")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def run_async(self, fn, *args):
        if self.busy:
            return
        self._set_busy(True)

        def worker():
            try:
                fn(*args)
            except Exception as e:  # noqa
                self.write(f"✘ Erro: {e}")
            finally:
                self.q.put(("done", None))

        threading.Thread(target=worker, daemon=True).start()

    # --------------------------------------------------------- process utils --
    def sh(self, cmd, stdin_text=None):
        self.write("$ " + (shlex.join(cmd) if not stdin_text else
                           shlex.join(cmd) + "   (senha oculta)"))
        p = subprocess.Popen(
            cmd, stdin=subprocess.PIPE if stdin_text else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            env=clean_env())
        if stdin_text:
            p.stdin.write(stdin_text)
            p.stdin.close()
        for line in p.stdout:
            self.write(line.rstrip())
        return p.wait()

    def capture(self, cmd):
        r = subprocess.run(cmd, capture_output=True, text=True, env=clean_env())
        return r.returncode, r.stdout.strip()

    def ask_priv(self):
        """Roda na thread principal. Retorna (prefixo, stdin) ou None."""
        if have("pkexec"):
            return ["pkexec"], None
        if have("sudo"):
            pw = simpledialog.askstring(
                "Senha", f"Senha de {getpass.getuser()} (sudo):", show="*",
                parent=self)
            if pw is None:
                return None
            return ["sudo", "-S", "-p", ""], pw + "\n"
        messagebox.showerror("Erro", "Nem pkexec nem sudo encontrados.\n"
                             "Instale o rclone manualmente: https://rclone.org/install/")
        return None

    def list_remotes(self):
        if not have("rclone"):
            return []
        rc, out = self.capture(["rclone", "listremotes"])
        return [l.rstrip(":") for l in out.splitlines() if l.strip()] if rc == 0 else []

    def refresh_remotes(self):
        remotes = self.list_remotes()
        self.cb_remote["values"] = remotes
        if remotes and not self.remote_var.get():
            self.remote_var.set(remotes[0])

    # -------------------------------------------------------------- actions --
    def on_browse(self):
        d = filedialog.askdirectory(initialdir=str(Path.home()),
                                    title="Pasta de montagem")
        if d:
            self.mount_var.set(d)

    # 1. instalar
    def on_install(self):
        if have("rclone") and fusermount_bin():
            self.write("✔ rclone e FUSE já estão instalados.")
            return
        priv = self.ask_priv()
        if priv is None:
            return
        self.run_async(self.do_install, priv)

    def do_install(self, priv):
        self.write(f"==> Distro detectada: {self.distro_name} "
                   f"(ID={self.distro_id}, ID_LIKE={self.distro_like})")
        pm, cmds = package_commands()
        if cmds:
            self.write(f"==> Instalando rclone + fuse3 via {pm}…")
            script = " && ".join(shlex.join(c) for c in cmds)
        elif have("curl"):
            self.write("==> Gerenciador não reconhecido; usando instalador oficial.")
            script = "curl -fsSL https://rclone.org/install.sh | bash"
        else:
            raise RuntimeError("Instale o rclone manualmente: https://rclone.org/install/")
        rc = self.sh(priv[0] + ["sh", "-c", script], stdin_text=priv[1])
        if rc != 0:
            raise RuntimeError(f"A instalação falhou (código {rc}).")
        if not fusermount_bin():
            self.write("⚠ fusermount/fusermount3 não encontrado. Instale o pacote fuse3 (ou fuse).")
        else:
            self.write("✔ Dependências instaladas.")

    # 2. remote
    def on_create_remote(self):
        if not have("rclone"):
            messagebox.showwarning("rclone ausente", "Instale as dependências primeiro (passo 1).")
            return
        name = self.remote_var.get().strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name or ""):
            messagebox.showwarning("Nome inválido", "Use apenas letras, números, _ . -")
            return
        if name in self.list_remotes():
            messagebox.showinfo("Já existe", f"O remote '{name}' já existe. Escolha outro nome.")
            return
        messagebox.showinfo(
            "Autorização",
            "O navegador será aberto para você autorizar o acesso.\n"
            "Depois de autorizar, volte para esta janela.")
        self.run_async(self.do_create_remote, name, self.type_var.get().strip())

    def do_create_remote(self, name, rtype):
        self.write(f"==> Criando remote '{name}' ({rtype})… aguardando autorização no navegador.")
        rc = self.sh(["rclone", "config", "create", name, rtype])
        if rc != 0:
            raise RuntimeError("Falha ao criar o remote. Tente 'rclone config (terminal)'.")
        self.write(f"✔ Remote '{name}' criado.")

    def on_config_terminal(self):
        if not have("rclone"):
            messagebox.showwarning("rclone ausente", "Instale as dependências primeiro (passo 1).")
            return
        cmd = find_terminal(["rclone", "config"])
        if not cmd:
            messagebox.showerror("Erro", "Nenhum emulador de terminal encontrado.\n"
                                 "Rode 'rclone config' manualmente.")
            return
        subprocess.Popen(cmd, env=clean_env())
        self.write("==> 'rclone config' aberto no terminal. Ao terminar, clique em 'Atualizar lista'.")

    # 3. serviço
    def on_service(self):
        remote = self.remote_var.get().strip()
        if not have("rclone"):
            messagebox.showwarning("rclone ausente", "Instale as dependências primeiro (passo 1).")
            return
        if not have("systemctl"):
            messagebox.showerror("Erro", "systemd não encontrado (Alpine/Void usam outro init).")
            return
        if remote not in self.list_remotes():
            messagebox.showwarning("Remote inexistente",
                                   f"O remote '{remote}' não existe. Crie-o no passo 2.")
            return
        if not fusermount_bin():
            messagebox.showerror("Erro", "fusermount/fusermount3 não encontrado. "
                                 "Instale o pacote fuse3 (passo 1).")
            return
        priv = None
        if self.linger_var.get():
            rc, out = self.capture(["loginctl", "show-user", getpass.getuser(),
                                    "-p", "Linger", "--value"])
            if out != "yes":
                priv = self.ask_priv()  # pode ser necessário
        mount_dir = os.path.expanduser(self.mount_var.get().strip())
        self.run_async(self.do_service, remote, mount_dir, self.linger_var.get(), priv)

    def do_service(self, remote, mount_dir, linger, priv):
        rclone_bin = shutil.which("rclone")
        fuse_bin = fusermount_bin()
        _, cfg = self.capture(["rclone", "config", "file"])
        cfg = cfg.splitlines()[-1].strip()

        self.write(f"==> Criando serviço para '{remote}' em {mount_dir}")
        Path(mount_dir).mkdir(parents=True, exist_ok=True)
        UNIT_DIR.mkdir(parents=True, exist_ok=True)

        unit = f"""[Unit]
Description=Rclone mount para {remote}
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
ExecStart={rclone_bin} mount {remote}: {mount_dir} \\
    --config={cfg} \\
    --vfs-cache-mode=full \\
    --dir-cache-time=1h \\
    --poll-interval=60s
ExecStop={fuse_bin} -uz {mount_dir}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
"""
        (UNIT_DIR / f"{SERVICE}.service").write_text(unit, encoding="utf-8")
        self.write(f"✔ Unit gravada em {UNIT_DIR / (SERVICE + '.service')}")

        if self.sh(["systemctl", "--user", "daemon-reload"]) != 0:
            raise RuntimeError("systemctl --user daemon-reload falhou.")
        if self.sh(["systemctl", "--user", "enable", "--now", f"{SERVICE}.service"]) != 0:
            self.write("Dica: veja o log com: journalctl --user -u rclone-mount -n 50")
            raise RuntimeError("Não foi possível iniciar o serviço.")

        if linger and priv is not None:
            user = getpass.getuser()
            rc = self.sh(["loginctl", "enable-linger", user])
            if rc != 0:
                self.sh(priv[0] + ["loginctl", "enable-linger", user], stdin_text=priv[1])
        self.write(f"✔ Pronto! '{remote}' montado em {mount_dir}")

    def on_status(self):
        self.run_async(lambda: self.sh(
            ["systemctl", "--user", "status", f"{SERVICE}.service", "--no-pager", "-n", "15"]))

    def on_remove(self):
        if not messagebox.askyesno("Confirmar", "Parar e remover o serviço de montagem?"):
            return
        self.run_async(self.do_remove)

    def do_remove(self):
        self.sh(["systemctl", "--user", "disable", "--now", f"{SERVICE}.service"])
        f = UNIT_DIR / f"{SERVICE}.service"
        if f.exists():
            f.unlink()
        self.sh(["systemctl", "--user", "daemon-reload"])
        self.write("✔ Serviço removido (seus dados na nuvem não foram tocados).")


if __name__ == "__main__":
    App().mainloop()
