#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail
cd "$(dirname "$0")"
echo "AI Factory Android builder"
echo "ملاحظة: هذا السكربت يبني تطبيق الواجهة الحالي فقط؛ لا يبني التطبيقات التي يولدها الذكاء الاصطناعي."
for cmd in java javac ecj dx aapt2 apksigner zip wget; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "خطأ: الأداة '$cmd' غير مثبتة."
    echo "أصلح مستودعات Termux أولاً، ثم ثبّت أدوات Android المطلوبة."
    exit 2
  fi
done
if [ ! -f AndroidManifest.xml ] || [ ! -f src/com/aifactory/app/MainActivity.java ]; then
  echo "خطأ: شغّل السكربت من مجلد AIFactoryApp الصحيح."; exit 2
fi
JAR="$PWD/android.jar"
if [ ! -s "$JAR" ]; then
  echo "تنزيل android.jar من مصدر Android platform archive..."
  wget -O "$JAR.tmp" "https://github.com/Sable/android-platforms/raw/master/android-30/android.jar"
  test -s "$JAR.tmp" || { rm -f "$JAR.tmp"; echo "فشل تنزيل android.jar"; exit 2; }
  mv "$JAR.tmp" "$JAR"
fi
rm -rf build && mkdir -p build/classes build/compiled
find src -name '*.java' > build/sources.txt
ecj -source 8 -target 8 -classpath "$JAR" -d build/classes @build/sources.txt
dx --dex --output=build/classes.dex build/classes
aapt2 compile --dir res -o build/compiled/res.zip
aapt2 link -o build/app.unsigned.apk -I "$JAR" --manifest AndroidManifest.xml -A assets --min-sdk-version 24 --target-sdk-version 28 build/compiled/res.zip
(cd build && zip -j app.unsigned.apk classes.dex >/dev/null)
[ -s my.keystore ] || keytool -genkeypair -keystore my.keystore -alias key -keyalg RSA -keysize 2048 -validity 10000 -storepass android -keypass android -dname "CN=AI Factory"
apksigner sign --ks my.keystore --ks-pass pass:android --key-pass pass:android --out AIFactory.apk build/app.unsigned.apk
echo "نجح بناء APK الواجهة: $PWD/build/AIFactory.apk"
if [ -d "$HOME/storage/downloads" ]; then cp build/AIFactory.apk "$HOME/storage/downloads/AIFactory.apk" && echo "نُسخ إلى Download"; fi
