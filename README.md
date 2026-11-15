# SPHEREx Sky Timeline

Reproductor del cielo infrarrojo de SPHEREx para el reto *Planet X and SPHEREx* (NASA Space Apps 2026). Muestra cada punto del cielo como un video: una línea de tiempo con todas las visitas de SPHEREx, seis canales de color, diferencia y suma de épocas, espectro y movimiento propio de cualquier fuente al hacer clic, y una capa de catálogo (Gaia DR3 y CatWISE2020) para confirmar lo que se ve moverse.

La pantalla de inicio tiene tres puertas, que son también los tres niveles de la app:

- **Aprende:** recorridos guiados (*El ciclo de la materia*, *Lo que se mueve*, *Estrellas que cambian*). Cada paso abre un objeto en el canal y modo correctos y explica qué mirar.
- **Descubre:** ~30 objetos por categoría (se mueven rápido, enanas marrones, cambian de brillo, polvo y hielo, galaxias), el reto *encuentra lo que se mueve* y el espectro con las bandas de agua, CO₂, CO, metano e hidrógeno explicadas.
- **Analiza:** tabla de objetos, espectro con errores, movimiento propio, banderas, metadatos y descarga de las medidas en CSV.

Los objetos y recorridos están en `ui/catalog.js`. Los 5 objetos principales tienen posición exacta y están modelados en la simulación; los demás se ubican con Sesame (CDS) al abrirlos, así que necesitan internet. Un recorrido se puede compartir con `?tour=cycle&step=2`.

El diseño y las decisiones de producto están en [`SPHEREx Sky Timeline diseño y features.md`](SPHEREx%20Sky%20Timeline%20diseño%20y%20features.md). La primera versión del motor estaba en Go (WebAssembly + raylib); ahora todo el código es Python y el navegador solo dibuja.

## Ejecutar

No hay paso de compilación: el servidor sirve `ui/` tal cual.

Con Nix:

```sh
nix develop          # o direnv allow; trae Python con numpy y astropy
serve-web            # http://localhost:8080 (PORT=… para cambiar el puerto)
```

Sin Nix (Python 3.10 o más reciente y numpy), desde la raíz del repositorio:

```sh
pip install numpy
python -m spherex    # http://localhost:8080
```

Opciones útiles:

| Opción | Qué hace |
|---|---|
| `--sim` | Solo simulación: no consulta IRSA ni Gaia (sirve sin internet). |
| `--addr 127.0.0.1:9000` | Dirección y puerto. |
| `--cache DIR` | Carpeta de la caché (por defecto `~/.cache/spherex-proxy`, la misma que usaba la versión en Go). |
| `--no-warm` | No precarga los 5 objetos de prueba al arrancar. |
| `-v` | Registro detallado. |

Sin `--sim` la app usa imágenes reales; `?data=sim` en la URL fuerza la simulación en esa pestaña.

Pruebas: `python -m pytest` (las de WCS se comparan además con astropy si está instalado; `tests/test_browser.py` corre la app en Chrome si hay `playwright`).

## Estructura

| Ruta | Qué hay |
|---|---|
| `spherex/server.py` | Servidor HTTP: la web, la API `/api/*` y la API del motor (eventos por SSE y comandos por POST). |
| `spherex/proxy.py` | Listas de imágenes, recortes y catálogos con caché en disco; precarga de los objetos de prueba. |
| `spherex/engine/` | Motor, uno por pestaña: carga de imágenes, composición (época, diferencia, suma), estiramiento, selección y medición. |
| `spherex/sky/` | Modelo de datos: campo, visitas, imágenes, simulación, reproyección de imágenes reales, fotometría y seguimiento. |
| `spherex/wcs.py` | Coordenadas: proyección TAN-SIP y tabla de longitudes de onda WAVE-TAB. |
| `spherex/fits.py` | Lectura y escritura mínima de FITS. |
| `spherex/irsa/` | Cliente de IRSA: SIA, TAP, recortes, CatWISE, caché en disco. |
| `spherex/gaia/` | Gaia DR3 desde el CDN de la ESA: HEALPix, descarga por rangos y teselas. |
| `ui/` | Interfaz HTML/CSS/JS; `viewer.js` dibuja el cielo en un canvas, `engine.js` habla con el motor y `catalog.js` tiene los objetos, recorridos y bandas. |
| `tests/` | Pruebas; `tests/data/` tiene un recorte real de Barnard y valores de referencia de astropy y de la versión en Go. |
| `docs/` | Documentación técnica y notebook explicativo. |

## Documentación

- [`docs/protocolos-y-datos.md`](docs/protocolos-y-datos.md): arquitectura, protocolos y métodos de transferencia, API, formatos, caché, concurrencia y tolerancia a fallos.
- [`docs/operaciones.ipynb`](docs/operaciones.ipynb): notebook que reproduce paso a paso cada operación del paquete con datos reales y la compara con astropy.

## Fuentes de datos

- SPHEREx DR1 y QR3: [IRSA](https://irsa.ipac.caltech.edu/Missions/spherex.html) (SIA, TAP y servicio de recortes).
- Gaia DR3: archivos masivos del [CDN de la ESA](https://cdn.gea.esac.esa.int/?prefix=Gaia/gdr3/).
- CatWISE2020: [IRSA](https://irsa.ipac.caltech.edu/) (TAP).
- Métodos basados en los [tutoriales de IRSA para SPHEREx y WISE](https://caltech-ipac.github.io/irsa-tutorials/).
