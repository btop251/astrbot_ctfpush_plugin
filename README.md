# 🚩 AstrBot CTF Pusher Plugin

<div align="center">

![AstrBot Plugin](https://img.shields.io/badge/AstrBot-Plugin-violet?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

**专业的 CTF 赛事情报订阅与 NSSCTF 随机刷题插件**

</div>

## ✨ 核心特性

- **📅 赛事日历**: 一键获取 CTFTime 全球即将开始的高质量赛事 (Weight > 0)。
- **🔔 智能订阅**: 支持按赛事 ID 或 **列表序号** 快速订阅，赛前 2 小时与 15 分钟自动提醒，不错过任何一场比赛。
- **🎲 随机刷题**: 集成 NSSCTF 题库，支持按 Web/Pwn/Crypto 等方向随机抽取题目，拒绝选择困难症。
- **🚀 零感持久化**: 基于 SQLite + SQLAlchemy，订阅数据自动保存，重启不丢失。

## 📦 安装指南

1. 确保已安装 AstrBot (V3/V4)。
2. 将本项目克隆至 AstrBot 的 `data/plugins/` 目录下：
   ```bash
   cd data/plugins/
   git clone https://github.com/btop251/astrbot_ctfpush_plugin.git
```

## 📚 指令手册

| 指令 | 描述 | 示例 |
| :--- | :--- | :--- |
| `/ctf` | 从nssctf跳题，支持分tag跳题 | `/ctf` 或 `/ctf pwn` |
| `/ctf订阅列表` | 查看已经订阅的赛事 | `/ctf订阅列表` |
| `/ctftime` | 查询 CTFTime 高权重 (>20) 国际赛事 | `/ctftime` |
| `/ctf订阅 <序号/ID>` | 订阅指定赛事（推荐先查询后按id订阅） | `/ctf订阅 3130` |
| `/ctf退定 <序号/ID>` | 退订指定赛事（推荐先查询后按id订阅） | `/ctf退订 3130` |

## 📄 配置说明 (\config.json\)

首次运行后会自动在插件目录下生成 \config.json\，支持热更新：

```json
{
  "ctftime": {
    "enabled": true,
    "limit": 50,
    "min_weight": 20.0,
    "request_timeout": 15
  },
  "subscription": {
    "scan_interval_minutes": 10,
    "remind_windows_minutes": [120, 15]
  }
}
```

## 🚀 开发计划

- [x] 迁移至 SQLite 数据库
- [x] 实现基于序号的退订功能
- [ ] 支持自定义提醒时间窗口

## 📄 License

MIT License
