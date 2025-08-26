# Force-Measurement (LIMB‑UCF)

**Python tools for collecting, visualizing, and analyzing muscle force data in LIMB lab experiments (e.g., MVC, force tracing, GDX sensors).**

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a> •
  <a href="#configuration">Configuration</a> •
</p>

---

## Features

- Real‑time force tracing (live plots or console output)  
- MVC measurement protocol with percent normalization  
- GDX sensor interface and test suite  
- Outputs in both CSV and JSON formats for easy downstream use

---

## Installation

```bash
git clone https://github.com/LIMB-UCF/Force-Measurement.git
cd Force-Measurement
python -m venv venv
source venv/bin/activate  # (or .\venv\Scripts\activate on Windows)
pip install -r requirements.txt
```

---

## Usage

### Force Measurement (Real‑Time)

```bash
python Force_Measurement_LIMBmk4.py
```

Real‑time acquisition of force signals. Supports live plotting and data saving (CSV/JSON).

### MVC Measurement

```bash
python MVC_Measurement_LIMB.py
```

Runs MVC trials per subject, stores raw values, and calculates percent MVC values.

### GDX Sensor Testing

```bash
python gdxtest.py
```

Verifies connection with GDX hardware; useful for debugging sensor setup.

---

## Configuration

| Option                        | Description                              |
|------------------------------|------------------------------------------|
| Trial durations & rest times | Modify directly in script or via CLI     |
| File naming / metadata       | Edit script header or configuration vars |
| Sensor port paths (GDX)      | Update based on your local setup         |

---

## File Structure

```
Force-Measurement/
├── data/
├── gdx/
├── Force_Measurement_LIMBmk4.py
├── MVC_Measurement_LIMB.py
├── gdxtest.py
├── mvc_percentages.csv/json
├── mvc_results.csv/json
└── requirements.txt
```
