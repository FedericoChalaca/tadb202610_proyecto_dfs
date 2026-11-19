# Centro de Mando

Tablero personal de una página que resume tu día a partir de Gmail y Google Calendar.
**Solo lectura:** pide los permisos `gmail.readonly` y `calendar.readonly`, así que no puede enviar, borrar, archivar ni marcar correos. Del correo solo guarda remitente, destinatarios, asunto, fecha, etiquetas e ID del hilo, nunca el cuerpo.

```
fetch_data.js      lee Gmail + Calendar  →  data/dashboard.json (+ dashboard.js)
src/compute.js     reglas: urgentes, sin respuesta, viajes, choques (función pura)
index.html         página autocontenida que muestra los datos
config.json        tu nombre, zona horaria, palabras clave, VIP, filtros de ruido
```

Requisitos: Node 20.12 o superior. No hay dependencias que instalar.

## 1. Conectar (una sola vez)

1. En <https://console.cloud.google.com> crea un proyecto y habilita **Gmail API** y **Google Calendar API**.
2. En **Google Auth Platform → Público**, configura la app como *Externa* y agrégate como usuario de prueba.
   Después pulsa **Publicar app** (pasar a *En producción*). Si la dejas en modo *Prueba*, Google vence el
   refresh token a los **7 días** y el refresco automático deja de funcionar. Para uso personal no necesitas
   verificación: verás un aviso de "app no verificada", que puedes aceptar.
3. En **Clientes**, crea un ID de cliente OAuth de tipo **App de escritorio**.
4. Copia las plantillas y pon tus datos:
   ```bash
   cp .env.example .env              # pega GOOGLE_CLIENT_ID y GOOGLE_CLIENT_SECRET
   cp config.example.json config.json  # tu nombre, tus correos, tus VIP
   ```
5. Autoriza:
   ```bash
   npm run auth
   ```
   Abre la URL que aparece, acepta, y el refresh token queda guardado en `.env`.

`.env`, `config.json` y `data/` están en `.gitignore`. No los subas.

## 2. Refrescar

```bash
npm run refresh     # lee Gmail + Calendar, regenera los datos y abre index.html
npm run fetch       # solo regenera los datos, sin abrir el navegador
```

Puedes abrir `index.html` con doble clic: los datos se cargan desde `data/dashboard.js`, así que no necesitas servidor.

## 3. Programarlo cada mañana a las 6:30

En cron no se abre el navegador: solo se regeneran los datos y tú abres el tablero cuando quieras.

**macOS / Linux** (`crontab -e`):

```cron
30 6 * * * cd "/ruta/a/centro-de-mando" && "$(command -v node)" fetch_data.js --quiet >> data/cron.log 2>&1
```

> En cron, `command -v node` puede fallar porque el PATH es mínimo. Pon la ruta absoluta que te da `which node`
> (por ejemplo `/opt/homebrew/bin/node`). La zona horaria es la del sistema, así que el equipo debe estar en
> hora de Colombia, y el computador tiene que estar encendido a esa hora.

**Windows** (Programador de tareas, en PowerShell):

```powershell
schtasks /Create /SC DAILY /ST 06:30 /TN "CentroDeMando" /TR "cmd /c cd /d C:\ruta\a\centro-de-mando && node fetch_data.js --quiet >> data\cron.log 2>&1"
```

## Ajustar las reglas (`config.json`)

| Clave | Qué hace |
|---|---|
| `myEmails` | Tus direcciones. Un hilo cuyo último mensaje sale de una de ellas cuenta como "respondido". |
| `actionKeywords`, `actionWindowDays` | Urgentes: no leídos o con estas palabras **en el asunto**, de los últimos N días. |
| `actionMatchBody` | `true` también cuenta coincidencias en el cuerpo. Viene apagado porque "favor" aparece en casi todo ("por favor"). |
| `unansweredMinDays`, `unansweredOnlyIfDirect` | Sin respuesta: más de N días y, si está activo, solo cuando estás en "Para" (no en copia). |
| `travelKeywords`, `travelSenders` | Viajes. Las alertas repetidas se agrupan en una sola fila. |
| `excludeCategories`, `excludeSenderPatterns`, `excludeSenders`, `excludeSubjectPatterns` | Filtros de ruido: newsletters, notificaciones, reportes automáticos. |
| `vipSenders` | Siempre pasan los filtros de ruido y aparecen primero. |

Al final de la página se ve cuántos correos se filtraron y por qué. Si algo importante no aparece, mira ahí primero.

## Probar sin credenciales

```bash
npm run fetch:raw   # usa data/raw.json (formato normalizado) en vez de la API
```
