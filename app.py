from flask import Flask, request, jsonify
import base64, math, random
from io import BytesIO
from datetime import datetime, timezone, timedelta
from PIL import Image
import piexif

app = Flask(__name__)

# ----- helpers -----
def decimal_to_exif_gps(value: float):
    v = abs(float(value))
    deg = int(v)
    minutes = int((v - deg) * 60)
    seconds = (v - deg - minutes / 60) * 3600
    return ((deg, 1), (minutes, 1), (int(seconds * 100), 100))

def math_cos_deg(deg: float):
    return math.cos(math.radians(deg))

def random_gps(lat0: float, lon0: float, meters: float = 2):
    r = math.sqrt(random.random()) * meters
    theta = random.uniform(0, 2 * math.pi)
    dx = r * math.cos(theta)
    dy = r * math.sin(theta)
    dlat = dy / 111320.0
    dlon = dx / (111320.0 * math_cos_deg(lat0))
    return lat0 + dlat, lon0 + dlon

def fmt_exif_time(dt: datetime):
    return dt.strftime("%Y:%m:%d %H:%M:%S")

def gps_time_tuple(dt: datetime):
    return ((dt.hour, 1), (dt.minute, 1), (dt.second, 1))

# ----- endpoint -----
@app.route("/procesar", methods=["POST"])
def procesar():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "JSON inválido"}), 400

    image_b64 = data.get("image_base64")
    lat = data.get("latitude")
    lon = data.get("longitude")
    if not image_b64 or lat is None or lon is None:
        return jsonify({"error": "Faltan campos: image_base64, latitude, longitude"}), 400

    # limpiar posible prefijo data:
    if isinstance(image_b64, str) and image_b64.startswith("data:image"):
        image_b64 = image_b64.split(",", 1)[1]

    # abrir imagen
    try:
        img = Image.open(BytesIO(base64.b64decode(image_b64)))
    except Exception as e:
        return jsonify({"error": f"No se pudo decodificar la imagen: {e}"}), 400

    # JPEG no soporta alpha
    if img.mode == "RGBA":
        img = img.convert("RGB")

    # tiempos: local + UTC (GPS)
    offset = timedelta(hours=1)  # +01:00
    now_local = datetime.now(timezone(offset))
    now_utc = now_local.astimezone(timezone.utc)
    subsec_ms = int(now_local.microsecond / 1000)
    offset_str = "+01:00"

    # GPS con variación ±2 m
    lat_rand, lon_rand = random_gps(float(lat), float(lon), meters=2)

    # construir EXIF
    exif = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
    # 0th
    exif["0th"][piexif.ImageIFD.Make] = "samsung"
    exif["0th"][piexif.ImageIFD.Model] = "Galaxy A54 5G"
    exif["0th"][piexif.ImageIFD.Software] = "A546BXXSCCYD1"
    exif["0th"][piexif.ImageIFD.DateTime] = fmt_exif_time(now_local)
    exif["0th"][piexif.ImageIFD.ImageDescription] = "Procesada: metadatos generados"
    exif["0th"][piexif.ImageIFD.Orientation] = 1  # horizontal

    # Exif (cámara)
    exif["Exif"][piexif.ExifIFD.ExposureTime] = (1, 221)
    exif["Exif"][piexif.ExifIFD.FNumber] = (18, 10)  # f/1.8
    exif["Exif"][piexif.ExifIFD.ISOSpeedRatings] = 40
    exif["Exif"][piexif.ExifIFD.ExposureProgram] = 2  # Program AE
    exif["Exif"][piexif.ExifIFD.ExifVersion] = b"0220"
    exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = fmt_exif_time(now_local)
    exif["Exif"][piexif.ExifIFD.DateTimeDigitized] = fmt_exif_time(now_local)
    exif["Exif"][piexif.ExifIFD.SubSecTimeOriginal] = f"{subsec_ms:03d}"
    exif["Exif"][piexif.ExifIFD.FocalLength] = (55, 10)  # 5.5mm
    exif["Exif"][piexif.ExifIFD.ColorSpace] = 1  # sRGB
    exif["Exif"][piexif.ExifIFD.PixelXDimension] = img.width
    exif["Exif"][piexif.ExifIFD.PixelYDimension] = img.height
    exif["Exif"][piexif.ExifIFD.ApertureValue] = (18, 10)
    # offsets de zona horaria
    exif["Exif"][piexif.ExifIFD.OffsetTime] = offset_str
    exif["Exif"][piexif.ExifIFD.OffsetTimeOriginal] = offset_str
    exif["Exif"][piexif.ExifIFD.OffsetTimeDigitized] = offset_str

    # GPS (UTC)
    exif["GPS"][piexif.GPSIFD.GPSLatitudeRef] = "N" if lat_rand >= 0 else "S"
    exif["GPS"][piexif.GPSIFD.GPSLatitude] = decimal_to_exif_gps(lat_rand)
    exif["GPS"][piexif.GPSIFD.GPSLongitudeRef] = "E" if lon_rand >= 0 else "W"
    exif["GPS"][piexif.GPSIFD.GPSLongitude] = decimal_to_exif_gps(lon_rand)
    exif["GPS"][piexif.GPSIFD.GPSDateStamp] = now_utc.strftime("%Y:%m:%d")
    exif["GPS"][piexif.GPSIFD.GPSTimeStamp] = gps_time_tuple(now_utc)
    # (sin altitud)

    # volcar y devolver
    exif_bytes = piexif.dump(exif)
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif_bytes, quality=95)
    buf.seek(0)

    filename = f"imagen_{now_local.strftime('%Y%m%d_%H%M%S')}.jpg"
    out_b64 = base64.b64encode(buf.read()).decode("utf-8")
    return jsonify({"filename": filename, "image_base64": out_b64})

if __name__ == "__main__":
    import os
    # Railway asigna el puerto en la variable de entorno PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
