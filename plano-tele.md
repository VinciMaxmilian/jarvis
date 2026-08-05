Área
Exemplos




Host
CPU %, RAM, commit, disco do sistema


Sensores
Temp CPU (LibreHardwareMonitor embutido), bateria (nível, saúde, Wh, taxa de carga)


Rede
Wi‑Fi (SSID, sinal dBm), interfaces


Disco
Volumes, SMART via smartctl embarcado


Inventário
OEM, placa-mãe, Windows build, módulos RAM, GPU, fans


Processos
Top CPU / Top RAM


Eventos
Eventos críticos do Windows


Agente
Versão, tamanho da fila offline

host_metrics

Tags: host
Fields: cpu/ram/disk/battery + commit_used_percent, commit_total_gb, commit_used_gb

wifi_status

Tags: host, interface — Fields: ssid, signal_dbm, connected

top_process

Tags: host, kind (cpu|ram), rank — Fields: name, pid, cpu_percent, working_set_mb

host_inventory

Tags: host — Fields: OEM, motherboard_, windows_, ram_, battery_ (battery_capacity_wh, battery_charge_rate_w assinado +/−, battery_power_state, battery_voltage_v, battery_temperature quando ACPI/Libre expõe), counts, etc.

gpu

Tags: host, name — Fields: adapter_ram_gb, driver_version, driver_date, temperature

ram_module

Tags: host, slot — Fields: + memory_type (DDR3/4/5…)

windows_event

Tags: host, type — Fields: event_id, provider, message, time_utc, bugcheck_code

agent_health

Tags: host — Fields: version, queue_count, queue_path

ssd_smart / disk_volume / temp_folder / network_interface / fan_metrics

(inalterados em conceito; ver docs anteriores)
Fila SQLite: somente host_metrics.