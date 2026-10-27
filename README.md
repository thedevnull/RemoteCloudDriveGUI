# Rclone Mount Setup (GUI)

Aplicativo gráfico simples, distribuído como AppImage, que:

1. detecta a distro Linux em uso;
2. instala as dependências (**rclone** e **FUSE**);
3. ajuda a configurar o remote (Google Drive, OneDrive, Dropbox etc.);
4. cria um serviço **systemd de usuário** que monta a nuvem em uma pasta automaticamente.

É a versão com interface do script `rclone-setup.sh`.

## Arquivos

| Arquivo | Função |
|---|---|
| `rclone_gui.py` | Aplicação (Python 3 + Tkinter) |
| `AppRun` | Ponto de entrada do AppImage; garante python3 + tkinter e abre a GUI |
| `rclone-gui.desktop` | Atalho / metadados do aplicativo |
| `rclone-gui.png` | Ícone |
| `build-appimage.sh` | Gera o `.AppImage` |

## Gerando o AppImage

Coloque todos os arquivos na mesma pasta e execute:

```bash
chmod +x build-appimage.sh AppRun
./build-appimage.sh
```

O script baixa o `appimagetool` (necessário acesso à internet) e gera
`RcloneMountSetup-x86_64.AppImage`. Para outra arquitetura, use `ARCH=aarch64 ./build-appimage.sh`.

## Usando

```bash
chmod +x RcloneMountSetup-x86_64.AppImage
./RcloneMountSetup-x86_64.AppImage
```

Ou dê duplo clique no arquivo no gerenciador de arquivos.

Para rodar sem empacotar (útil para testes):

```bash
python3 rclone_gui.py
```

### Passo a passo na janela

1. **Dependências**: clique em *Instalar dependências*. A senha é pedida por uma janela do sistema (`pkexec`) ou, se ele não existir, por um campo de senha do `sudo`.
2. **Remote**: informe um nome (ex.: `gdrive`), escolha o tipo (ex.: `drive`) e clique em *Criar remote*. O navegador abrirá para você autorizar o acesso. Para configurações mais avançadas, use *rclone config (terminal)*. Se você já tem remotes, basta selecioná-lo na lista.
3. **Montagem**: escolha a pasta (padrão: `~/GoogleDrive`), marque *linger* se quiser montar no boot mesmo sem login, e clique em *Criar serviço e montar*.

Os botões *Ver status* e *Parar e remover serviço* ajudam a gerenciar o serviço depois.

## Distros e gerenciadores suportados

| Gerenciador | Distros típicas |
|---|---|
| `pacman` | Arch, Manjaro, EndeavourOS |
| `apt-get` | Debian, Ubuntu, Mint, Pop!_OS |
| `dnf` | Fedora, RHEL e derivadas |
| `zypper` | openSUSE |
| `apk` | Alpine (sem systemd, a montagem automática não funciona) |
| `xbps-install` | Void (sem systemd, a montagem automática não funciona) |

Se nenhum for reconhecido, o app usa o instalador oficial (`https://rclone.org/install.sh`), desde que o `curl` esteja instalado.

## Requisitos

- Linux com **systemd** (para o serviço de montagem).
- **python3 com tkinter**. Se faltar, o `AppRun` instala automaticamente (`python3-tk`, `python3-tkinter` ou `tk`, conforme a distro), o que exige `pkexec` (polkit) ou `sudo` em terminal.
- Não execute como root: o serviço é instalado para o usuário atual.

## O que é criado no seu sistema

- Serviço: `~/.config/systemd/user/rclone-mount.service`
- Pasta de montagem: a que você escolher (padrão `~/GoogleDrive`)
- Configuração do rclone: a padrão (`rclone config file`), normalmente `~/.config/rclone/rclone.conf`

O serviço usa o rclone **instalado no sistema**, não o de dentro do AppImage, então continua funcionando mesmo se você apagar o AppImage.

Opções de montagem usadas: `--vfs-cache-mode=full`, `--dir-cache-time=1h`, `--poll-interval=60s`, com reinício automático em caso de falha.

## Comandos úteis

```bash
systemctl --user status rclone-mount          # status
journalctl --user -u rclone-mount -n 50       # logs
systemctl --user restart rclone-mount         # reiniciar
systemctl --user disable --now rclone-mount   # parar e desativar
```

## Solução de problemas

- **"fusermount/fusermount3 não encontrado"**: instale o pacote `fuse3` (ou `fuse`) pelo passo 1.
- **Serviço não inicia**: veja `journalctl --user -u rclone-mount -n 50`. Causas comuns são a pasta de montagem não estar vazia ou o token do remote ter expirado (refaça a autorização com `rclone config reconnect NOME:`).
- **Navegador não abre na criação do remote**: use *rclone config (terminal)* e siga o assistente.
- **AppImage não abre por falta de FUSE no sistema**: rode com `./RcloneMountSetup-x86_64.AppImage --appimage-extract-and-run`.
- **Nenhum emulador de terminal encontrado**: rode `rclone config` manualmente.

## Desinstalar

Use *Parar e remover serviço* na janela, ou manualmente:

```bash
systemctl --user disable --now rclone-mount
rm ~/.config/systemd/user/rclone-mount.service
systemctl --user daemon-reload
```

Isso não apaga seus dados na nuvem nem o remote configurado no rclone.
