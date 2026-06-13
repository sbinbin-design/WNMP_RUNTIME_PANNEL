# WNMP Panel v0.1.1-dev Release Notes

## IE11 兼容修复

- 修复 Windows Server 2016 IE11 下环境信息区域布局重叠问题：改为单列纵向布局，卡片不卡死、不重叠、文字可读、按钮可点击
- 修复 IE11 下 MySQL 初始密码弹窗不可见/不居中问题：使用 absolute + transform 居中方案替代 flex 居中
- 修复 IE11 下右下角 Toast 提示块宽度塌陷和中文逐字换行问题：设置固定安全宽度，确保横向排版稳定
- 修复 IE11 下环境信息路径文本在 125%/150% 缩放时挤压布局问题：允许路径自然换行

## 功能修复

- 修复初始化按钮无响应问题
- 修复中英文切换后部分文案未更新问题

## 文案优化

- MySQL 初始密码弹窗文案优化：明确说明密码仅在本弹窗中自动显示一次，关闭后面板不会再次显示

## 版本号统一管理

- 版本号统一由根目录 VERSION 文件管理，运行时优先读取 VERSION 文件，version.py 仅提供兜底值
- WNMPPanel.exe 内嵌 manifest 版本号由 sync_version.py 从 VERSION 自动生成，确保一致性
- 不在前端文件中写死版本号

## 核心逻辑不变

- 本版本不改变 Nginx / PHP / MySQL 核心启停逻辑
- 不改变初始化流程
- 不改变状态判断和状态刷新逻辑
- 不改变语言切换业务语义
- 不改变 Nginx / PHP / MySQL 配置生成逻辑
- 不改变随机启动逻辑
- 不改变日志查看逻辑
- 不需要重新初始化环境

---

## 下一开发阶段调整：组件配置路径归位（P2-A）

> 注意：以下为开发阶段调整说明，不影响 v0.1.1-dev 已发布版本的历史事实。

- Nginx 活跃配置正式切换到 `bin/nginx/conf/` 目录（nginx.conf、site.conf、vhosts/、custom/http/、custom/server/）
- PHP 活跃配置正式切换到 `bin/php/` 目录（php.ini、php-cgi.ini、php.user.ini）
- MySQL 活跃配置正式切换到 `bin/mysql/my.ini`（my.user.ini 同理）
- Panel 自身配置保留在 `config/runtime.ini`，不移动
- 旧 `config/nginx/`、`config/php/`、`config/mysql/` 下文件保留不删，仅作为迁移来源
- 模板文件迁移到 `runtime/templates/` 对应组件目录，不再作为 config 下的运行依赖
- 新增非覆盖迁移逻辑：旧配置存在且新目标不存在时复制；新目标已存在但未被 Panel 管理时先备份再覆盖；已被 Panel 管理时不覆盖
- 原始配置备份保存在 `config/backups/original/<component>/`
- MySQL 数据目录保持 `data/mysql/`，日志目录保持 `logs/`，均不迁入组件目录
