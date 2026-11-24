import fastf1

try:
    session = fastf1.get_session(2025, 1, "R")
    session.load(telemetry=False, laps=False, weather=False)

    drivers = session.drivers
    if drivers:
        drv_num = drivers[0]
        info = session.get_driver(drv_num)
        print("Driver Info Keys for Round 1:")
        for key, value in info.items():
            print(f"  {key}: {value}")
except Exception as e:
    print(f"Error: {e}")
