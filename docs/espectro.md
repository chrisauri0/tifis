# Qué dice el espectro

Cómo Tifis pasa de los puntos del espectro de una fuente a «esto se parece a una enana marrón T» o «esto cambió entre temporadas». El código está en `spherex/espectro.py` (análisis) y `spherex/features.py` (tabla de firmas y reglas). El motor lo corre en un hilo aparte cada vez que se mide una selección y manda el resultado en el evento `analysis`. También se puede usar desde la terminal:

```sh
python -m spherex.espectro spherex/seleccion.json --por-temporada
python -m spherex.espectro medidas.json --sistema-solar --json
```

El JSON de entrada es el del evento `select` (la lista `measurements`) o el que descarga el botón *Descargar análisis (JSON)* en el nivel *Analiza*.

## Una sola tabla de firmas

`spherex/features.py` es la única fuente de verdad. El análisis la lee y el servidor la sirve en `GET /api/features`; `ui/catalog.js` ya no tiene su propia lista y dibuja las bandas con lo que le da el servidor.

Cada firma tiene: rango en µm (`lo`, `hi`), tipo esperado (`abs`, `emi` o `either`), si es una línea que SPHEREx no resuelve (`line`), con qué continuo se mide (`planck` o `local`), qué familias de objetos indica (`classes`), con qué se confunde (`confuses`) y una explicación en español e inglés.

| Firma | µm | Tipo | Indica |
|---|---|---|---|
| H₂O gas | 1.30–1.50, 1.75–2.05, 2.55–2.85 | abs | Atmósferas frías: enanas marrones, enanas M, gigantes rojas |
| CH₄ | 1.60–1.80, 2.15–2.29, 3.20–3.45 | abs | Enanas marrones T y Y (la más discriminante es 3.3 µm) |
| CO gas | 2.29–2.50, 4.45–4.85 | abs | Gigantes rojas, enanas L; en enanas Y, mezcla desde capas calientes |
| H₂O hielo | 2.90–3.25 | abs | Nubes frías; asteroides hidratados |
| CO₂ | 4.20–4.35 | abs o emi | Hielo en nubes (absorción); gas en la coma de un cometa (emisión) |
| CO hielo | 4.63–4.71 | abs | Corazón de nubes frías (< 20 K) |
| He I 1.083, Paβ 1.282, Paα 1.875, H₂ 2.122, Brγ 2.166, Brα 4.051 | ±0.6 elementos de resolución | emi (líneas) | Estrellas jóvenes, acreción, gas ionizado |
| PAH | 3.24–3.35 | emi | Moléculas orgánicas en nebulosas y galaxias |

Las longitudes de onda son valores de laboratorio; las referencias están en el encabezado de `features.py` (Cushing et al. 2005, Kirkpatrick 2005, Boogert et al. 2015, Tielens 2008, NIST ASD y Doré et al. 2014 para la resolución). La resolución usada es λ/Δλ = 41 (0.75–2.42 µm), 35 (2.42–3.82), 110 (3.82–4.42) y 130 (4.42–5.00). Si el equipo encuentra un valor mejor en la literatura, se cambia solo ahí.

## Tres capas

### 1. Continuo

El continuo es un cuerpo negro por unidad de frecuencia, B_ν, porque SPHEREx mide F_ν. Se ajusta fuera de todas las bandas de la tabla; los puntos que quedan muy por debajo se descartan como absorción, pero nunca más del 35 % (en una variable, «bajo» puede ser solo «medido en el mínimo»). La química es la desviación de ese continuo: r(λ) = F_obs / F_Planck, con r < 1 absorción y r > 1 emisión.

Hay cuatro variantes, y el análisis elige sola:

- **Una escala** (lo normal).
- **Una escala por visita**, si el objeto varía (ver abajo) y eso mejora mucho el ajuste. Los seis canales de una visita se miden a la vez, así que cada visita es un espectro instantáneo de baja resolución y los colores salen de ahí, aunque el brillo cambie entre visitas.
- **Una temperatura y una escala por visita**, suavizadas en el tiempo (mediana a ±20 días), para variables que cambian de color con la fase, como las Miras. Se reporta el rango de T.
- **Estrella + disco** (dos cuerpos negros), cuando hay exceso infrarrojo: la T de la estrella sale de λ < 2.3 µm y la del disco se busca entre 300 y 1500 K.

Con `--sistema-solar` (o `analyze(..., solar_system=True)`) el continuo es luz del Sol reflejada (5800 K por un albedo gris) más emisión térmica propia (100–700 K). Da la T térmica y qué fracción de la luz a 4.6 µm es térmica. Para tamaño y albedo hacen falta las distancias al Sol y a la Tierra (efemérides), que la app todavía no tiene.

### 2. Firmas con significancia

La profundidad de cada banda se mide con pesos de varianza inversa, así que el error sale directo:

```
d = 1 − Σ w·(F/F_cont) / Σ w,   w = (F_cont/σ)²,   σ_d = 1/√Σw,   z = d/σ_d
```

Solo cuentan los puntos donde el continuo se habría detectado (F_cont > 3σ). Si el continuo ajusta peor de lo que dicen los errores (χ² reducido > 1), σ_d se multiplica por √χ²: una enana marrón no es un cuerpo negro y sus profundidades no son tan precisas como dirían los errores de las medidas.

Para emisión, PAH, CO₂ y el hielo de CO se usa un **continuo local**: el continuo global corregido por una recta ajustada en dos ventanas a cada lado de la banda. Se mide en dos pasadas: primero las bandas anchas contra el cuerpo negro; luego las locales, con ventanas que esquivan las bandas ya detectadas (salvo la que contiene a la firma, como el agua de 1.9 µm para Paα). Una línea sin ventanas limpias no se mide: junto al borde de una banda ancha, cualquier «bulto» sería el borde.

El estado de cada firma, con la significancia en el sentido esperado:

| Estado | Criterio |
|---|---|
| `detectada` | z ≥ 3 en una banda ancha |
| `compatible` | z ≥ 3 en una línea no resuelta («compatible con», nunca «detectada») |
| `indicio` | 2 ≤ z < 3 |
| `opuesta` | z ≤ −3 (p. ej. absorción donde se esperaba emisión de PAH: es el metano) |
| `no` | lo demás |

Además hay señales que no son bandas: `ir_excess` (luz a 3.8–5 µm sobre el cuerpo negro de < 2.3 µm, solo en estrellas detectadas en el corto y con T > 2500 K), `very_cold` (T de color < 700 K) y `thermal` (en el modelo del sistema solar).

### 3. Clasificación por reglas

Cada regla de `RULES` tiene un rango de temperatura de color (con bordes suaves, porque la T de color es aproximada), firmas que quiere (con peso), firmas que suman si están (`bonus`) y firmas que la descartan (`avoid`). El puntaje va de 0 a 1:

- cada firma aporta `clip((z − 1)/4, 0, 1)`: z ≤ 1 no cuenta, z ≥ 5 cuenta completo;
- se promedia con los pesos sobre las firmas medidas y se multiplica por √(fracción del peso que se pudo medir);
- `bonus` suma hasta 0.3; `avoid` multiplica por (1 − la más fuerte); el rango de T multiplica por 1 dentro y baja a 0 un 15 % fuera.

El resultado es una lista ordenada con puntajes y con las firmas a favor, en contra y sin medir. No es un veredicto.

Familias: enana marrón T/Y, enana L o M tardía, gigante roja, detrás de una nube fría con hielo, estrella joven con disco, nebulosa o galaxia con formación estelar, estrella sin firmas fuertes; y con el modelo del sistema solar: cometa, asteroide hidratado y asteroide seco.

## Cambio en el tiempo

Las temporadas son las del motor (visitas separadas por más de 40 días). `analyze_seasons` analiza todo junto y cada temporada por separado, y compara temporadas consecutivas:

- **Variabilidad, sin modelo.** Pares de medidas casi a la misma λ (menos de ¼ de elemento de resolución) tomadas con días de diferencia deberían coincidir. La mediana de |ΔF|/σ, dividida entre 0.674 (su valor en ruido puro), da la razón. En los objetos de prueba sale < 1.3 en los estables y 5–16 en RW Aur y R Dra; el umbral es 2.5.
- **Brillo**: Δmag a 1.2, 2.2 y 4.6 µm medido en los datos (el modelo de una temporada solo corrige que la otra midió en otras λ).
- **Temperatura**: ΔT con su error (más 1 % sistemático). Solo cuenta si el objeto también varía: en un objeto que no es cuerpo negro, la T de color se mueve con las λ que tocó medir.
- **Firmas**: el cociente F/continuo de una temporada se interpola en las λ de la otra y se comparan en las mismas λ, con 0.025 de sistemático por temporada. Cuenta si supera 3σ (con ~17 firmas, 2σ daría casi siempre un falso cambio).

## Límites que muestra la interfaz

- **El espectro no es simultáneo.** Cada λ se mide en otra visita. En una variable, la forma del espectro combinado mezcla química con tiempo; por eso el análisis por temporada y la escala o T por visita.
- **Resolución baja.** Las líneas salen como bultos: «compatible con».
- **En enanas marrones la T de color no es la efectiva.** Para clasificar pesan más las bandas que T.
- **Moléculas que comparten rango** (CH₄ y CO cerca de 2.3 µm; CO₂ hielo y gas a 4.27 µm; CH₄ y PAH a 3.3 µm). Cada firma muestra su `confuses`.
- Durante una misión de *Descubre* la interpretación se oculta, porque daría la respuesta.

## Verificación

`tests/test_espectro.py` comprueba la tabla, la matemática de la profundidad, espectros sintéticos con respuesta conocida (cuerpo negro, enana T, gigante roja, hielos, línea de emisión, estrella con disco, enana Y, cometa), que no se inventen líneas en bordes de banda, la prueba de variabilidad, que un objeto estable no cambie entre temporadas y una pulsante sí, y los 5 objetos de prueba simulados:

| Objeto | Clasificación | Varía |
|---|---|---|
| Barnard's Star | estrella sin firmas fuertes | no |
| Epsilon Indi B | enana marrón T/Y | no |
| WISE 0855−0714 | enana marrón T/Y | no |
| RW Aurigae | estrella joven con disco | sí |
| R Draconis | gigante roja | sí |

`spherex/seleccion.json` (datos reales de Epsilon Indi B) también sale como enana marrón T/Y.
