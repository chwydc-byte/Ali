import json, os, time, re, zipfile, io
from pathlib import Path
from typing import Literal
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

APP_DIR = Path(__file__).resolve().parent
DB = APP_DIR / "projects.json"
OUT = APP_DIR / "generated"
OUT.mkdir(exist_ok=True)

app = FastAPI(title="AI Factory API", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

Kind = Literal["android_app", "game_2d", "game_3d"]
class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Kind
    prompt: str = Field(min_length=10, max_length=20000)
class GenerateRequest(ProjectRequest):
    project_id: int | None = None

STEPS = {
 "android_app":["تحليل المتطلبات","تحديد الشاشات والتنقل","إنشاء هيكل Android","تنفيذ الوظائف","اختبارات أولية","بناء APK وتوقيعه"],
 "game_2d":["تحليل أسلوب اللعب","إنشاء مشروع Godot 2D","الشخصيات والتحكم","المراحل والتصادم","اختبار الأداء","تصدير Android APK"],
 "game_3d":["تحليل المشاهد والتحكم","إنشاء مشروع Godot 3D","الشخصيات والمجسمات","الإضاءة والصوت","اختبار وتحسين الأداء","تصدير Android APK"]
}
def load():
    try: return json.loads(DB.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError): return []
def save(rows): DB.write_text(json.dumps(rows, ensure_ascii=False, indent=2), "utf-8")
def plan(r):
    return f"المشروع: {r.name}\\nالنوع: {r.kind}\\n\\nالمتطلبات:\\n{r.prompt}\\n\\nخطة التنفيذ:\\n" + "\\n".join(f"{i+1}. {s}" for i,s in enumerate(STEPS[r.kind]))
def safe_name(s):
    s=re.sub(r"[^A-Za-z0-9_-]+","_",s).strip("_")
    return (s or "AIProject")[:48]
@app.get("/health")
def health():
    return {"status":"ok","service":"AI Factory API","version":"1.0.0",
            "ai_configured":bool(os.getenv("AI_API_KEY")),"capabilities":["planning","project_storage","source_scaffold","ai_code_generation_if_configured"]}
@app.post("/projects/plan")
def make_plan(r:ProjectRequest):
    return {"status":"ok","plan":plan(r),"steps":STEPS[r.kind]}
@app.post("/projects")
def create(r:ProjectRequest):
    rows=load(); item={"id":int(time.time()*1000),"name":r.name,"kind":r.kind,"prompt":r.prompt,
        "plan":plan(r),"status":"planned","created_at":int(time.time())}
    rows.insert(0,item); save(rows); return item
@app.get("/projects")
def projects(): return load()
@app.delete("/projects/{pid}")
def delete(pid:int):
    rows=load(); new=[x for x in rows if x["id"]!=pid]
    if len(rows)==len(new): raise HTTPException(404,"project not found")
    save(new); return {"deleted":pid}
@app.post("/generate")
async def generate(r:GenerateRequest):
    """Generate a source bundle. AI generation requires an OpenAI-compatible endpoint and server-side key."""
    key=os.getenv("AI_API_KEY"); endpoint=os.getenv("AI_BASE_URL","https://api.openai.com/v1").rstrip("/")
    model=os.getenv("AI_MODEL","gpt-4.1-mini")
    if not key:
        # Safe fallback: provide a useful project brief and Android starter scaffold, never pretend this is a complete app.
        files = scaffold(r)
        mode="starter_scaffold"
    else:
        prompt = ("You are a senior Android/Godot engineer. Return ONLY a JSON object mapping relative file paths to full UTF-8 text contents. "
          "Generate a small, runnable starter project matching the request. For android_app use a standard Gradle Android project with Kotlin/Compose. "
          "For game_2d/game_3d generate Godot 4 project.godot and minimal scenes/scripts. Do not include secrets, binaries, or claims that APK was built. "
          "Limit to 20 files and 100KB total. Include README_AR.md with build instructions. Request type: "+r.kind+
          "\\nProject name: "+r.name+"\\nUser requirements:\\n"+r.prompt)
        try:
            async with httpx.AsyncClient(timeout=180) as c:
                resp=await c.post(endpoint+"/chat/completions",headers={"Authorization":f"Bearer {key}"},
                    json={"model":model,"temperature":0.2,"messages":[{"role":"system","content":"Return valid JSON only."},{"role":"user","content":prompt}]})
            resp.raise_for_status()
            content=resp.json()["choices"][0]["message"]["content"]
            content=re.sub(r"^```(?:json)?\\s*|\\s*```$","",content.strip())
            files=json.loads(content)
            if not isinstance(files,dict) or not files: raise ValueError("AI returned no files")
            files={str(k):str(v) for k,v in list(files.items())[:20] if not str(k).startswith("/") and ".." not in Path(str(k)).parts}
            if sum(len(v.encode()) for v in files.values())>100_000: raise ValueError("generated source exceeds size limit")
            mode="ai_generated_source"
        except Exception as e:
            raise HTTPException(502, f"AI generation failed: {type(e).__name__}. Check AI_BASE_URL, AI_MODEL and server logs.")
    slug=safe_name(r.name); folder=OUT/f"{slug}_{int(time.time())}"; folder.mkdir(parents=True,exist_ok=True)
    for rel,content in files.items():
        dest=(folder/rel).resolve()
        if folder.resolve() not in dest.parents: continue
        dest.parent.mkdir(parents=True,exist_ok=True); dest.write_text(content,encoding="utf-8")
    (folder/"AI_FACTORY_REPORT_AR.txt").write_text(
      f"اسم المشروع: {r.name}\\nالنوع: {r.kind}\\nوضع الإنشاء: {mode}\\n\\nتنبيه: هذا مصدر أولي، وليس APK مبنيًا أو مختبرًا. افتح README_AR.md واتبع خطوات البناء ثم اختبر على جهاز حقيقي.\\n",
      encoding="utf-8")
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        for f in folder.rglob("*"):
            if f.is_file(): z.write(f,f.relative_to(folder))
    buf.seek(0)
    return StreamingResponse(buf,media_type="application/zip",headers={"Content-Disposition":f'attachment; filename="{slug}_source.zip"',
        "X-AI-Factory-Mode":mode})
def scaffold(r):
    name=safe_name(r.name)
    readme=f"""# {r.name}
## متطلبات المستخدم
{r.prompt}

## الحالة
هذه حزمة بداية مولدة تلقائياً وليست تطبيقاً كاملاً أو APK جاهزاً. أكمل الوظائف، ثم ابنِ واختبر.
"""
    if r.kind=="android_app":
        return {
          "README_AR.md":readme+"\\nيتطلب Android SDK وGradle. افتح المشروع في Android Studio أو بيئة بناء Android متوافقة.\\n",
          "settings.gradle.kts":'pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\\ndependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }\\nrootProject.name = "'+name+'"\\ninclude(":app")\\n',
          "build.gradle.kts":'plugins { id("com.android.application") version "8.7.3" apply false; id("org.jetbrains.kotlin.android") version "2.0.21" apply false; id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false }\\n',
          "gradle.properties":"org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8\\nandroid.useAndroidX=true\\n",
          "app/build.gradle.kts":'plugins { id("com.android.application"); id("org.jetbrains.kotlin.android"); id("org.jetbrains.kotlin.plugin.compose") }\\nandroid { namespace = "com.aifactory.generated"; compileSdk = 35; defaultConfig { applicationId = "com.aifactory.generated"; minSdk = 26; targetSdk = 35; versionCode = 1; versionName = "1.0" } ; buildFeatures { compose = true } }\\ndependencies { implementation(platform("androidx.compose:compose-bom:2024.12.01")); implementation("androidx.activity:activity-compose:1.9.3"); implementation("androidx.compose.material3:material3"); implementation("androidx.compose.ui:ui"); implementation("androidx.compose.ui:ui-tooling-preview") }\\n',
          "app/src/main/AndroidManifest.xml":'<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:theme="@android:style/Theme.Material.Light.NoActionBar" android:label="'+r.name.replace("&","&amp;")+'"><activity android:name=".MainActivity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>\\n',
          "app/src/main/java/com/aifactory/generated/MainActivity.kt":'package com.aifactory.generated\\n\\nimport android.os.Bundle\\nimport androidx.activity.ComponentActivity\\nimport androidx.activity.compose.setContent\\nimport androidx.compose.foundation.layout.*\\nimport androidx.compose.material3.*\\nimport androidx.compose.runtime.*\\nimport androidx.compose.ui.Alignment\\nimport androidx.compose.ui.Modifier\\nimport androidx.compose.ui.unit.dp\\n\\nclass MainActivity : ComponentActivity() { override fun onCreate(savedInstanceState: Bundle?) { super.onCreate(savedInstanceState); setContent { MaterialTheme { var count by remember { mutableIntStateOf(0) }; Surface(Modifier.fillMaxSize()) { Column(Modifier.fillMaxSize().padding(24.dp), verticalArrangement=Arrangement.Center, horizontalAlignment=Alignment.CenterHorizontally) { Text("'+r.name.replace('"',"'")+'", style=MaterialTheme.typography.headlineMedium); Spacer(Modifier.height(16.dp)); Text("نموذج أولي مبني على فكرتك"); Text("طلباتك: '+r.prompt[:180].replace('"',"'")+'"); Spacer(Modifier.height(16.dp)); Button(onClick={count++}) { Text("تجربة الوظيفة: $count") } } } } } } }\\n'
        }
    # Godot starter templates, with explicit note that custom assets/gameplay still need implementation.
    return {
      "README_AR.md":readme+"\\nافتح هذا المجلد باستخدام Godot 4.3 أو أحدث. لتصدير Android يلزم إعداد Android SDK/JDK وقوالب التصدير داخل Godot.\\n",
      "project.godot":f'config_version=5\\n\\n[application]\\nconfig/name="{r.name.replace(chr(34), chr(39))}"\\nrun/main_scene="res://Main.tscn"\\n\\n[display]\\nwindow/size/viewport_width=720\\nwindow/size/viewport_height=1280\\nwindow/stretch/mode="canvas_items"\\n',
      "Main.tscn":'[gd_scene load_steps=2 format=3]\\n\\n[ext_resource type="Script" path="res://main.gd" id="1"]\\n\\n[node name="Main" type="Node2D"]\\nscript = ExtResource("1")\\n',
      "main.gd":'extends Node2D\\n\\nvar elapsed := 0.0\\nfunc _ready():\\n    print("AI Factory starter: '+r.name.replace('"',"'")+'")\\nfunc _process(delta):\\n    elapsed += delta\\n    queue_redraw()\\nfunc _draw():\\n    draw_rect(Rect2(Vector2.ZERO, get_viewport_rect().size), Color("#080d1b"))\\n    draw_string(ThemeDB.fallback_font, Vector2(32, 80), "'+r.name.replace('"',"'")+'", HORIZONTAL_ALIGNMENT_LEFT, -1, 32, Color("#52e5ff"))\\n    draw_string(ThemeDB.fallback_font, Vector2(32, 130), "Starter scene - implement gameplay from prompt", HORIZONTAL_ALIGNMENT_LEFT, -1, 18, Color.WHITE)\\n'
    }
