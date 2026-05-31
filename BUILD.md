# 打包说明

## 环境要求

- Windows 10 / 11（必须在 Windows 上打包，否则无法生成可用的 exe）
- Python 3.10 或更高版本
- 网络连接（首次运行需下载依赖）

---

## 快速打包

在项目目录下，**双击运行 `build_exe.bat`**，脚本会自动完成依赖安装和打包。

输出文件位于：

```
dist/WeChatAntiRevoke.exe
```

---

## 手动打包步骤

如果批处理脚本无法运行，可按以下步骤手动操作。

**1. 安装依赖**

```bash
pip install customtkinter pyinstaller
```

**2. 执行打包**

```bash
pyinstaller build.spec --clean
```

**3. 取出 exe**

打包完成后，`dist/WeChatAntiRevoke.exe` 即为单文件可执行程序，可独立分发，无需 Python 环境。

---

## 打包产物说明

| 路径 | 说明 |
|------|------|
| `dist/WeChatAntiRevoke.exe` | 最终可执行文件，体积约 30–50 MB |
| `build/` | 打包中间文件，可删除 |

---

## 常见问题

**杀毒软件报警？**

PyInstaller 打包的 exe 因为使用了通用壳，常被误报。可以：
- 将文件添加到杀毒软件白名单
- 使用自己的代码签名证书对 exe 进行签名

**打包后运行时报「找不到模块」？**

通常是 customtkinter 的资源文件未打入包内。确认 `build.spec` 中的 `datas` 包含了 customtkinter 目录：

```python
import customtkinter
CTK_DIR = os.path.dirname(customtkinter.__file__)

datas=[
    ('data/patch.json', 'data'),
    (CTK_DIR, 'customtkinter'),
],
```

**exe 启动后界面空白或崩溃？**

以管理员身份打开命令提示符，切换到 `dist/` 目录，直接运行 exe 查看错误输出：

```bat
cd dist
WeChatAntiRevoke.exe
```

**想修改版本号或图标？**

在 `build.spec` 的 `EXE(...)` 中添加：

```python
exe = EXE(
    ...
    name='WeChatAntiRevoke',
    icon='assets/icon.ico',      # 自定义图标
    version='version_info.txt',  # 自定义版本信息
)
```

版本信息文件格式参考 [PyInstaller 文档](https://pyinstaller.org/en/stable/usage.html#capturing-windows-version-data)。
