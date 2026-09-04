# SocialReader 公开演示版

这是求职演示入口，只读取 `data/demo-data.json` 中的已归档快照，不访问本机 API，也不执行小红书或抖音实时采集。

重新生成脱敏演示数据：

```powershell
D:\Python312\python.exe D:\SocialReader\public-demo\build_demo_data.py
```

实时采集仍由项目根目录的 `start_food_demo.bat` 在本机运行。
