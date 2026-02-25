import fastf1

try:
    # Try loading the last race of 2025 to get a driver list
    session = fastf1.get_session(2025, 'Abu Dhabi', 'R')
    session.load()
    drivers = session.drivers
    print("Driver numbers:", drivers)
    for drv_num in drivers:
        driver_info = session.get_driver(drv_num)
        print(f"{driver_info['Abbreviation']} - {driver_info['FullName']} - {driver_info['TeamName']}")

except Exception as e:
    print(f"Error: {e}")
