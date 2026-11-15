// Objects, guided tours and spectral bands for the three doors of the app
// (Learn, Discover, Analyze). Texts are bilingual: { es, en }.
//
// An object either points at one of the engine's built-in targets (`target`:
// exact positions, and modeled in the simulation too) or is looked up by name
// in Sesame (`query`, a SIMBAD identifier) when opened, like the search box
// does, so positions and proper motions come from SIMBAD and not from here.
// `band` is 0-based (channel 1 = 0); `fov` in arcmin.

export const CATEGORIES = [
  { id: 'moving', icon: '→', name: { es: 'Se mueven rápido', en: 'Fast movers' },
    hint: { es: 'Estrellas cercanas que cruzan el cielo en pocos años. Usa Diferencia.', en: 'Nearby stars that cross the sky in a few years. Use Difference.' } },
  { id: 'brown', icon: '◐', name: { es: 'Enanas marrones', en: 'Brown dwarfs' },
    hint: { es: '“Estrellas fallidas”: frías, con agua y metano en su atmósfera.', en: '“Failed stars”: cold, with water and methane in their atmospheres.' } },
  { id: 'variable', icon: '∿', name: { es: 'Cambian de brillo', en: 'Changing brightness' },
    hint: { es: 'Estrellas que pulsan o parpadean. Usa Época y dale play.', en: 'Stars that pulse or flicker. Use Epoch and press play.' } },
  { id: 'dust', icon: '❄', name: { es: 'Polvo, hielo y estrellas naciendo', en: 'Dust, ice and newborn stars' },
    hint: { es: 'Nubes frías y nebulosas: compara canales cortos y largos.', en: 'Cold clouds and nebulae: compare short and long channels.' } },
  { id: 'galaxy', icon: '✺', name: { es: 'Galaxias', en: 'Galaxies' },
    hint: { es: 'Galaxias cercanas; a 3.3 µm brillan moléculas orgánicas (PAH).', en: 'Nearby galaxies; organic molecules (PAHs) glow at 3.3 µm.' } },
];

export const OBJECTS = [
  // ---------- Fast movers ----------
  { id: 'barnard', target: 'barnard', cat: ['moving'], band: 1, mode: 'diff', fov: 6,
    desc: { es: 'La estrella que más rápido cruza el cielo: 10.4″ por año.', en: 'The fastest-moving star on the sky: 10.4″ per year.' } },
  { id: 'kapteyn', name: "Kapteyn's Star", query: "Kapteyn's star", cat: ['moving'], band: 1, mode: 'diff', fov: 6,
    desc: { es: 'Una estrella vieja del halo de la galaxia, que va a contracorriente del disco.', en: 'An old halo star moving against the rotation of the disk.' } },
  { id: 'groombridge1830', name: 'Groombridge 1830', query: 'Groombridge 1830', cat: ['moving'], band: 1, mode: 'diff', fov: 6,
    desc: { es: 'Otra estrella del halo, pobre en metales y muy veloz.', en: 'Another fast, metal-poor halo star.' } },
  { id: 'wolf359', name: 'Wolf 359', query: 'Wolf 359', cat: ['moving'], band: 1, mode: 'diff', fov: 6,
    desc: { es: 'Una enana roja a menos de 8 años luz.', en: 'A red dwarf less than 8 light years away.' } },
  { id: 'lalande21185', name: 'Lalande 21185', query: 'Lalande 21185', cat: ['moving'], band: 1, mode: 'diff', fov: 6,
    desc: { es: 'Una de las enanas rojas más brillantes del cielo norte, con planetas.', en: 'One of the brightest red dwarfs in the northern sky, with planets.' } },
  { id: '61cyg', name: '61 Cygni', query: '61 Cyg A', cat: ['moving'], band: 1, mode: 'diff', fov: 6,
    desc: { es: 'La primera estrella cuya distancia se midió (Bessel, 1838).', en: 'The first star to have its distance measured (Bessel, 1838).' } },
  { id: 'proxima', name: 'Proxima Centauri', query: 'Proxima Centauri', cat: ['moving'], band: 1, mode: 'diff', fov: 6,
    desc: { es: 'La estrella más cercana al Sol, a 4.2 años luz.', en: 'The star closest to the Sun, 4.2 light years away.' } },
  { id: 'teegarden', name: "Teegarden's Star", query: "Teegarden's star", cat: ['moving'], band: 1, mode: 'diff', fov: 6,
    desc: { es: 'Una enana roja muy tenue con planetas parecidos a la Tierra.', en: 'A very faint red dwarf with Earth-like planets.' } },
  // ---------- Brown dwarfs ----------
  { id: 'eps-indi-b', target: 'eps-indi-b', cat: ['brown', 'moving'], band: 2, mode: 'diff', fov: 6,
    desc: { es: 'Dos enanas marrones vecinas, a 12 años luz.', en: 'Two neighboring brown dwarfs, 12 light years away.' } },
  { id: 'wise0855', target: 'wise0855', cat: ['brown', 'moving'], band: 5, mode: 'diff', fov: 6,
    desc: { es: 'La enana marrón más fría conocida: invisible en el canal 1, clara en el 6.', en: 'The coldest known brown dwarf: invisible in channel 1, clear in 6.' } },
  { id: 'luhman16', name: 'Luhman 16', query: 'Luhman 16', cat: ['brown', 'moving'], band: 2, mode: 'diff', fov: 6,
    desc: { es: 'El par de enanas marrones más cercano, a 6.5 años luz.', en: 'The closest pair of brown dwarfs, 6.5 light years away.' } },
  { id: 'gj229b', name: 'Gliese 229 B', query: 'GJ 229 B', cat: ['brown'], band: 3, mode: 'epoch', fov: 6,
    desc: { es: 'La primera enana marrón con metano confirmada (1995), junto a una estrella brillante.', en: 'The first confirmed methane brown dwarf (1995), next to a bright star.' } },
  // ---------- Changing brightness ----------
  { id: 'r-dra', target: 'r-dra', cat: ['variable'], band: 2, mode: 'epoch', fov: 6,
    desc: { es: 'Una gigante tipo Mira que pulsa cada 245 días.', en: 'A Mira giant that pulses every 245 days.' } },
  { id: 'rw-aur', target: 'rw-aur', cat: ['variable', 'dust'], band: 3, mode: 'epoch', fov: 6,
    desc: { es: 'Una estrella joven con disco que se apaga y enciende sin aviso.', en: 'A young star with a disk that dims and brightens without warning.' } },
  { id: 'mira', name: 'Mira (ο Ceti)', query: 'Mira', cat: ['variable'], band: 2, mode: 'epoch', fov: 6,
    desc: { es: 'La primera variable descubierta (1596); pulsa cada 332 días. Tan brillante que satura.', en: 'The first variable star found (1596); pulses every 332 days. So bright it saturates.' } },
  { id: 'chicyg', name: 'χ Cygni', query: 'chi Cyg', cat: ['variable'], band: 2, mode: 'epoch', fov: 6,
    desc: { es: 'Una Mira de las que más cambian: miles de veces entre máximo y mínimo en luz visible.', en: 'One of the Miras that changes most: thousands of times between maximum and minimum in visible light.' } },
  { id: 'rleo', name: 'R Leonis', query: 'R Leo', cat: ['variable'], band: 2, mode: 'epoch', fov: 6,
    desc: { es: 'Una gigante roja pulsante, de las más fáciles de seguir.', en: 'A pulsating red giant, one of the easiest to follow.' } },
  { id: 'irc10216', name: 'CW Leonis (IRC +10216)', query: 'IRC +10216', cat: ['variable', 'dust'], band: 4, mode: 'epoch', fov: 6,
    desc: { es: 'Una estrella de carbono envuelta en el polvo que expulsa; brilla mucho en el infrarrojo largo.', en: 'A carbon star wrapped in the dust it sheds; very bright in the long infrared.' } },
  { id: 'ttau', name: 'T Tauri', query: 'T Tau', cat: ['variable', 'dust'], band: 3, mode: 'epoch', fov: 6,
    desc: { es: 'El prototipo de estrella recién nacida, todavía rodeada de gas y polvo.', en: 'The prototype newborn star, still surrounded by gas and dust.' } },
  { id: 'fuori', name: 'FU Orionis', query: 'FU Ori', cat: ['variable', 'dust'], band: 3, mode: 'epoch', fov: 6,
    desc: { es: 'Una estrella joven que en 1937 aumentó su brillo más de cien veces en pocos meses.', en: 'A young star that brightened more than a hundredfold within months in 1937.' } },
  // ---------- Dust, ice and star formation ----------
  { id: 'b68', name: 'Barnard 68', query: 'Barnard 68', cat: ['dust'], band: 0, mode: 'epoch', fov: 12,
    desc: { es: 'Una nube oscura que tapa las estrellas de atrás; el infrarrojo largo la atraviesa.', en: 'A dark cloud hiding the stars behind it; long infrared gets through.' } },
  { id: 'tmc1', name: 'TMC-1 (Tauro)', query: 'TMC-1', cat: ['dust'], band: 3, mode: 'epoch', fov: 12,
    desc: { es: 'Una nube fría de Tauro, rica en moléculas y hielos.', en: 'A cold cloud in Taurus, rich in molecules and ices.' } },
  { id: 'l1688', name: 'ρ Ophiuchi (L1688)', query: 'LDN 1688', cat: ['dust'], band: 3, mode: 'epoch', fov: 12,
    desc: { es: 'Una de las guarderías de estrellas más cercanas, a ~450 años luz.', en: 'One of the nearest stellar nurseries, ~450 light years away.' } },
  { id: 'm42', name: 'Nebulosa de Orión (M42)', query: 'M 42', cat: ['dust'], band: 3, mode: 'epoch', fov: 12,
    desc: { es: 'La gran fábrica de estrellas cercana; gas encendido por estrellas jóvenes.', en: 'The great nearby star factory; gas lit up by young stars.' } },
  { id: 'ngc7023', name: 'Nebulosa del Iris (NGC 7023)', query: 'NGC 7023', cat: ['dust'], band: 3, mode: 'epoch', fov: 12,
    desc: { es: 'Una nebulosa de reflexión famosa por sus moléculas orgánicas (PAH) a 3.3 µm.', en: 'A reflection nebula famous for its organic molecules (PAHs) at 3.3 µm.' } },
  // ---------- Galaxies ----------
  { id: 'm82', name: 'Galaxia del Cigarro (M82)', query: 'M 82', cat: ['galaxy'], band: 3, mode: 'epoch', fov: 12,
    desc: { es: 'Una galaxia que forma estrellas a toda velocidad; su polvo brilla en el infrarrojo.', en: 'A galaxy forming stars at full speed; its dust glows in the infrared.' } },
  { id: 'm51', name: 'Galaxia del Remolino (M51)', query: 'M 51', cat: ['galaxy'], band: 3, mode: 'epoch', fov: 12,
    desc: { es: 'Una espiral de frente con su galaxia compañera.', en: 'A face-on spiral with its companion galaxy.' } },
  { id: 'ngc253', name: 'Galaxia del Escultor (NGC 253)', query: 'NGC 253', cat: ['galaxy'], band: 3, mode: 'epoch', fov: 12,
    desc: { es: 'Una espiral polvorienta y brillante; más grande que el campo, se ve su centro.', en: 'A bright, dusty spiral; larger than the field, its center is shown.' } },
];

// Guided tours of the Learn door. Each step opens an object with a view and
// explains what to look at; `actions` are buttons that switch the view.
export const TOURS = [
  {
    id: 'cycle',
    title: { es: 'El ciclo de la materia', en: 'The cycle of matter' },
    summary: {
      es: 'Las estrellas fabrican carbono y oxígeno, lo sueltan como polvo, en el polvo se congelan hielos y de esas nubes nacen estrellas y planetas nuevos.',
      en: 'Stars make carbon and oxygen, shed it as dust, ices freeze on that dust, and new stars and planets are born from those clouds.',
    },
    steps: [
      { object: 'r-dra', view: { band: 2, mode: 'epoch' }, play: true,
        title: { es: 'Una estrella que suelta su material', en: 'A star shedding its material' },
        text: {
          es: 'R Draconis es una gigante roja al final de su vida. Pulsa cada ~245 días y en cada pulso expulsa gas con carbono y oxígeno que ella misma fabricó. Mira cómo cambia su brillo entre visitas.',
          en: 'R Draconis is a red giant near the end of its life. It pulses every ~245 days, and each pulse throws out gas with carbon and oxygen it made itself. Watch its brightness change between visits.',
        } },
      { object: 'b68', view: { band: 0, mode: 'epoch' },
        title: { es: 'El material se enfría: polvo y hielo', en: 'The material cools: dust and ice' },
        text: {
          es: 'Barnard 68 es una nube oscura de polvo y gas frío. El polvo tapa las estrellas de atrás, pero el infrarrojo largo lo atraviesa mejor: compara el canal 1 con el 6 y fíjate en cuántas estrellas aparecen. En nubes así, el agua y el CO₂ se congelan sobre los granos de polvo.',
          en: 'Barnard 68 is a dark cloud of cold dust and gas. The dust hides the stars behind it, but long infrared gets through better: compare channel 1 with 6 and count how many stars show up. In clouds like this, water and CO₂ freeze onto the dust grains.',
        },
        actions: [{ band: 0, label: { es: 'Canal 1 (0.75 µm)', en: 'Channel 1 (0.75 µm)' } }, { band: 5, label: { es: 'Canal 6 (4.4 µm)', en: 'Channel 6 (4.4 µm)' } }] },
      { object: 'rw-aur', view: { band: 3, mode: 'epoch' }, play: true,
        title: { es: 'En las nubes nacen estrellas', en: 'Stars are born in the clouds' },
        text: {
          es: 'RW Aurigae es una estrella joven, todavía rodeada del disco de gas y polvo donde se forman los planetas. El disco brilla en el infrarrojo y a ratos la tapa: por eso parpadea sin un ritmo fijo.',
          en: 'RW Aurigae is a young star, still surrounded by the disk of gas and dust where planets form. The disk glows in the infrared and now and then hides the star: that is why it flickers with no fixed rhythm.',
        } },
      { object: 'wise0855', view: { band: 5, mode: 'epoch' },
        title: { es: 'Lo más frío: casi un planeta', en: 'The coldest: almost a planet' },
        text: {
          es: 'WISE 0855 es una enana marrón a unos 0 °C: no tiene masa para encenderse como estrella. En el canal 1 no se ve; en el 6, donde emite su calor, aparece. Su atmósfera tiene agua y metano, como Júpiter. El carbono y el oxígeno de todo esto, y de ti, pasaron por este ciclo.',
          en: 'WISE 0855 is a brown dwarf at about 0 °C: not massive enough to ignite as a star. In channel 1 it is invisible; in 6, where it gives off its heat, it appears. Its atmosphere has water and methane, like Jupiter. The carbon and oxygen in all of this, and in you, went through this cycle.',
        },
        actions: [{ band: 0, label: { es: 'Canal 1', en: 'Channel 1' } }, { band: 5, label: { es: 'Canal 6', en: 'Channel 6' } }] },
    ],
  },
  {
    id: 'moving',
    title: { es: 'Lo que se mueve', en: 'What moves' },
    summary: {
      es: 'Algunas estrellas cercanas se desplazan tanto que SPHEREx las ve moverse en pocos meses.',
      en: 'Some nearby stars move so much that SPHEREx sees them shift within a few months.',
    },
    steps: [
      { object: 'barnard', view: { band: 1, mode: 'diff', catalog: true }, play: true,
        title: { es: 'La estrella más rápida', en: 'The fastest star' },
        text: {
          es: 'En Diferencia, lo que no cambia queda gris. La estrella de Barnard deja un par blanco y negro: blanco donde está en esta visita, negro donde estaba en la época de referencia (A). Avanza 10.4″ por año, más de un píxel y medio. La flecha azul sale de su posición en el catálogo Gaia (2016) y apunta adonde debería estar en esta fecha.',
          en: 'In Difference, whatever does not change turns gray. Barnard’s Star leaves a white-and-black pair: white where it is at this visit, black where it was at the reference epoch (A). It moves 10.4″ per year, more than one and a half pixels. The blue arrow starts at its Gaia catalog position (2016) and points to where it should be on this date.',
        } },
      { object: 'eps-indi-b', view: { band: 2, mode: 'diff', catalog: true }, play: true,
        title: { es: 'Enanas marrones de paseo', en: 'Brown dwarfs on the move' },
        text: {
          es: 'Epsilon Indi B son dos enanas marrones a 12 años luz. Avanzan unos 4.7″ por año hacia el sureste: menos de un píxel, así que el par blanco y negro es más tenue.',
          en: 'Epsilon Indi B is a pair of brown dwarfs 12 light years away. They move about 4.7″ per year toward the southeast: less than a pixel, so the black-and-white pair is fainter.',
        } },
      { object: 'wise0855', view: { band: 5, mode: 'diff', catalog: true }, play: true,
        title: { es: 'Solo se ve en el infrarrojo largo', en: 'Only visible in the long infrared' },
        text: {
          es: 'WISE 0855 es tan fría que solo aparece en el canal 6, y aun así se mueve 8.1″ por año hacia el oeste.',
          en: 'WISE 0855 is so cold it only shows up in channel 6, and it still moves 8.1″ per year toward the west.',
        } },
      { object: 'kapteyn', view: { band: 1, mode: 'diff', catalog: true }, play: true,
        title: { es: 'Una estrella que va a contracorriente', en: 'A star going against the flow' },
        text: {
          es: 'La estrella de Kapteyn es vieja y viene del halo de la galaxia: gira al revés que el Sol. Por eso pasa tan rápido a nuestro lado, unos 8.7″ por año. ¿Quieres intentarlo tú? En Descubre hay un reto para encontrar lo que se mueve.',
          en: 'Kapteyn’s Star is old and comes from the galactic halo: it orbits backwards compared with the Sun. That is why it races past us at about 8.7″ per year. Want to try yourself? The Discover door has a challenge to find what moves.',
        } },
    ],
  },
  {
    id: 'variable',
    title: { es: 'Estrellas que cambian', en: 'Stars that change' },
    summary: {
      es: 'Unas estrellas pulsan con un ritmo; otras parpadean sin aviso. SPHEREx las sigue por meses.',
      en: 'Some stars pulse with a rhythm; others flicker without warning. SPHEREx follows them for months.',
    },
    steps: [
      { object: 'r-dra', view: { band: 2, mode: 'epoch' }, play: true,
        title: { es: 'Una Mira: pulsos de 245 días', en: 'A Mira: 245-day pulses' },
        text: {
          es: 'R Draconis crece y se encoge con un ritmo de 245 días. Haz clic sobre la estrella: debajo de la línea de tiempo aparece su curva de luz, el brillo medido en cada visita.',
          en: 'R Draconis swells and shrinks every 245 days. Click on the star: its light curve, the brightness measured at each visit, appears under the timeline.',
        } },
      { object: 'rw-aur', view: { band: 3, mode: 'epoch' }, play: true,
        title: { es: 'Parpadeo de una estrella joven', en: 'A young star flickering' },
        text: {
          es: 'RW Aurigae no tiene periodo: su disco de polvo la tapa a ratos. Selecciónala y compara su curva de luz con la de R Draconis.',
          en: 'RW Aurigae has no period: its dusty disk hides it now and then. Select it and compare its light curve with R Draconis’.',
        } },
      { object: 'mira', view: { band: 2, mode: 'epoch' }, play: true,
        title: { es: 'La primera variable conocida', en: 'The first known variable' },
        text: {
          es: 'Mira fue la primera estrella que se vio cambiar (1596) y pulsa cada 332 días. Es tan brillante que satura el detector: el centro sale aplanado, pero el halo alrededor crece y se encoge con el pulso.',
          en: 'Mira was the first star seen to change (1596) and pulses every 332 days. It is so bright it saturates the detector: the core is flattened, but the halo around it grows and shrinks with the pulse.',
        } },
    ],
  },
];

// Spectral bands drawn on the spectrum and explained in the band list.
export const BANDS = [
  { id: 'h2o14', label: 'H₂O', l: 1.4, w: 0.12,
    desc: { es: 'Vapor de agua en atmósferas frías: enanas marrones y gigantes rojas.', en: 'Water vapor in cool atmospheres: brown dwarfs and red giants.' } },
  { id: 'h2o19', label: 'H₂O', l: 1.9, w: 0.15,
    desc: { es: 'Más vapor de agua; en enanas marrones casi apaga la luz aquí.', en: 'More water vapor; in brown dwarfs it nearly blacks out the light here.' } },
  { id: 'co23', label: 'CO', l: 2.3, w: 0.1,
    desc: { es: 'Monóxido de carbono en gigantes rojas frías y enanas marrones calientes.', en: 'Carbon monoxide in cool red giants and warm brown dwarfs.' } },
  { id: 'ice30', label: 'H₂O ❄', l: 3.05, w: 0.18,
    desc: { es: 'Hielo de agua sobre granos de polvo en nubes frías; se ve como absorción en la luz de estrellas de fondo.', en: 'Water ice on dust grains in cold clouds; seen as absorption in the light of background stars.' } },
  { id: 'ch433', label: 'CH₄', l: 3.32, w: 0.08,
    desc: { es: 'Metano en enanas marrones frías. En nebulosas y galaxias, a 3.3 µm brillan moléculas orgánicas (PAH).', en: 'Methane in cold brown dwarfs. In nebulae and galaxies, organic molecules (PAHs) glow at 3.3 µm.' } },
  { id: 'bra', label: 'Brα', l: 4.05, w: 0.04,
    desc: { es: 'Hidrógeno ionizado por estrellas jóvenes y calientes (nebulosas): una línea de emisión.', en: 'Hydrogen ionized by young, hot stars (nebulae): an emission line.' } },
  { id: 'co2', label: 'CO₂ ❄', l: 4.27, w: 0.06,
    desc: { es: 'Hielo de dióxido de carbono en nubes frías.', en: 'Carbon dioxide ice in cold clouds.' } },
  { id: 'co47', label: 'CO', l: 4.67, w: 0.08,
    desc: { es: 'Monóxido de carbono, como gas (enanas marrones) o como hielo (nubes).', en: 'Carbon monoxide, as gas (brown dwarfs) or as ice (clouds).' } },
];

export const findObject = (id) => OBJECTS.find((o) => o.id === id);
