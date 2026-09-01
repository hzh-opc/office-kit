# Linux 平台字体安装

本目录是 `doc-layout-aesthetics` 字体包在 **Linux** 平台上的**专用安装资源**。
跨平台共用的字体二进制（OTF/TTF/TTC）在 `../common/` 下，跨平台安装脚本在
`../install_fonts.sh`。

## Debian / Ubuntu（apt）

```bash
# TrueType 轮廓（reportlab PDF 可嵌入）
sudo apt install fonts-wqy-zenhei fonts-dejavu-core fonts-lxgw-wenkai

# 注意：fonts-noto-cjk 是 CFF/TTC 轮廓，reportlab 不能嵌入 PDF——
# 脚本会自动跳过；思源/Noto CJK 仍可用于 HTML/系统显示
sudo apt install fonts-noto-cjk    # 可选（Word/HTML 用）
```

## CentOS / RHEL / Fedora（dnf）

```bash
sudo dnf install wqy-zenhei-fonts dejavu-sans-mono-fonts google-noto-sans-cjk-sc-fonts
```

## Arch / Manjaro（pacman）

```bash
sudo pacman -S --noconfirm wqy-zenhei ttf-dejavu noto-fonts-cjk \
                            wqy-microhei   # 微米黑（TrueType 备选）
```

## 国内镜像（apt）

如 apt 源慢或失败，可改用清华 / 阿里 / 中科大镜像：

```bash
# 清华 TUNA
sudo sed -i 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g; s|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' /etc/apt/sources.list

# 阿里云
sudo sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list
```

## 离线安装

```bash
# 从 ../common/ 复制到 ~/.local/share/fonts 并刷新缓存
bash ../install_fonts.sh
fc-cache -f -v
```

## 验证安装

```bash
fc-list | grep -iE "lxgw|wqy|sourcehan|noto.*sc" | head
```
