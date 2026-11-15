# SPHEREx Sky Timeline: diseño y features

Nov 12, 2026 · @Barac Fabregat

## Lo que los datos imponen

Tres hechos de los datos de SPHEREx condicionan el diseño; las features salen de ahí.

1. **Cada imagen de un mismo punto está en una longitud de onda distinta.** Animar las imágenes crudas en orden temporal hace que todo parpadee por color, no por movimiento. Hay que agrupar por detector: cada apuntado produce 6 archivos, uno por detector ([Data Products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products)), con rangos de 0.75–1.1, 1.1–1.6, 1.6–2.4, 2.4–3.8, 3.8–4.4 y 4.4–5.0 µm ([IRSA](https://irsa.ipac.caltech.edu/Missions/spherex.html)).
2. **Los píxeles son grandes: unos 6" (aproximado, de memoria; no verificado en estas páginas).** WISE 0855 y la estrella de Barnard se mueven del orden de 8–10" por año, cerca de un píxel por año. El movimiento no salta a la vista en un blink simple, así que la resta de épocas y el seguimiento de centroide son el núcleo del producto.
3. **El acceso es simple y por URL.** Un recorte se pide añadiendo `center` y `size` a la URL del archivo ([Cutout Tool](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html)). La lista de imágenes que cubren una coordenada sale de SIA2 ([Data Access](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access)) o de una consulta TAP que devuelve URL y fecha de cada recorte ([tutorial](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts)). Cada recorte trae las capas IMAGE, FLAGS, VARIANCE, ZODI, PSF y WCS-WAVE, así que banderas y espectros salen del mismo archivo.

Pendiente: no se pudo abrir la pestaña Resources del reto (el sitio bloquea el acceso automático); falta revisar si hay enlaces extra ahí.

## Concepto: una línea de tiempo del cielo

La pantalla es un reproductor de video: el cielo en el centro, una línea de tiempo abajo y seis "canales" de color al lado. Quien nunca ha visto un FITS entiende play, pausa y arrastrar.

## Features

El MVP es un reproductor de épocas por canal con URL compartible; la resta de épocas y el espectro al clic son lo que lo hace destacar.

### Imprescindibles (MVP)

- **Búsqueda** por coordenadas en cualquier formato (`08h55m10.8s -07d14m42s` o grados) y por nombre de objeto, resolviendo con Sesame de CDS.
- **Los 5 objetos de prueba como tarjetas de inicio** ("Empieza aquí: la estrella más rápida del cielo"), cada una con una frase de qué buscar.
- **Reproductor de épocas**: play/pausa, velocidad, arrastre, flechas del teclado. Los fotogramas se apilan por detector y por visita.
- **Selector de 6 canales** con colores fijos y nombres humanos ("1.6–2.4 µm · hielo de agua").
- **URL compartible**: `?ra=…&dec=…&fov=…&band=…&mode=…`, más un modo `embed` sin controles.
- **Campo de visión ajustable** con aviso del costo ("más cielo = más descarga").

### Las que hacen destacar

- **Modo Diferencia**: época B menos época A. Un objeto que se movió aparece como par blanco/negro; una variable (RW Aur, R Dra) como un punto que late.
- **Modo Suma**: apilar épocas para sacar objetos débiles.
- **Espectro al clic**: al tocar una fuente, panel con sus puntos de brillo contra longitud de onda (fotometría de apertura simple sobre los recortes), con bandas de H₂O, CO₂ y CO marcadas.
- **Curva de luz** en la misma línea de tiempo, para las variables.
- **Capa Gaia/WISE**: marcadores de catálogo con flechas de movimiento propio. Si una flecha coincide con lo que se ve moverse, el usuario "confirma" su hallazgo.
- **Banderas visibles**: píxeles contaminados sombreados, con un interruptor y texto al pasar el cursor.

### Extra si sobra tiempo

- Composición RGB de tres canales.
- "Marcar candidato": guarda coordenada, época y nota, y exporta enlace o GIF.
- Tutorial guiado de 60 segundos con Barnard.
- Indicador "datos hasta la semana X". El archivo recibe imágenes nuevas cada semana ([QR Overview](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html)), así que consultando en vivo no hay nada que actualizar a mano.

## Principios de UI/UX

Lo avanzado aparece solo al pedirlo; la primera pantalla es play y canales.

- **Tres niveles**: Explorar (solo play y canales), Comparar (resta/suma, capas), Analizar (espectro, banderas, metadatos).
- **Carga progresiva**: primer fotograma en 1–2 s, el resto llega mientras ya se reproduce; la línea de tiempo muestra qué está cargado.
- **Lenguaje llano primero**, término técnico en segundo plano ("Canal 4 · 2.4–3.8 µm").
- **Accesibilidad**: todo por teclado, paletas aptas para daltonismo, respeto a "reducir movimiento", y español/inglés.
- **Honestidad visual**: mostrar el tamaño real del píxel y una escala en segundos de arco, para que nadie confunda ruido con descubrimiento.

## Stack: raylib + Go + WASM

Hay tres riesgos que conviene resolver el primer día, antes de escribir features.

- [ ] **raylib-go usa cgo**, que no compila directo a WASM con el toolchain estándar.

  Existen bindings alternativos para web; verificar que uno funcione con un "hola mundo" antes de comprometerse.
- [ ] **Una UI dibujada entera en canvas es invisible para lectores de pantalla**, y maneja mal texto, teclado móvil y traducción.

  Recomendación: un híbrido. HTML/CSS para buscador, controles y paneles; raylib/WASM solo para el visor (render, blink, resta, zoom). Go también puede hacer el parseo de FITS y la fotometría.
- [ ] **Comprobar si IRSA permite peticiones desde el navegador (CORS).**

  Si no, hace falta un proxy pequeño en Go, que de paso sirve para cachear y para descartar la capa PSF: llega completa en cada recorte y es un cubo de 121 planos ([Data Products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products)).

Siguiente paso propuesto: un mockup de la pantalla principal (reproductor, canales y panel de espectro) para fijar el layout antes del código.

## Fuentes

- [SPHEREx Archive User Guide: Data Access](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-access)
- [SPHEREx Archive User Guide: Data Products](https://caltech-ipac.github.io/spherex-archive-documentation/spherex-data-products)
- [SPHEREx Cutout Capabilities (IRSA)](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/cutout_tool.html)
- [IRSA tutorial: SPHEREx cutouts](https://caltech-ipac.github.io/irsa-tutorials/spherex-cutouts)
- [SPHEREx en IRSA](https://irsa.ipac.caltech.edu/Missions/spherex.html)
- [SPHEREx Quick Release Overview](https://irsa.ipac.caltech.edu/data/SPHEREx/docs/overview_qr.html)
- [SPHEREx: NASA's Near-Infrared Spectrophotometric All-Sky Survey (arXiv)](https://arxiv.org/pdf/2404.11017)
- [Reto Planet X and SPHEREx (Space Apps 2026)](https://www.spaceappschallenge.org/2026/challenges/planet-x-and-spherex/?tab=details)
