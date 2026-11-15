// Objects, guided tours and spectral bands for the three doors of the app
// (Learn, Discover, Analyze); the bands come from the server. Texts are bilingual: { es, en }.
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
  { id: 'r-dra', rhythm: 'periodic', target: 'r-dra', cat: ['variable'], band: 2, mode: 'epoch', fov: 6,
    desc: { es: 'Una gigante tipo Mira que pulsa cada 245 días.', en: 'A Mira giant that pulses every 245 days.' } },
  { id: 'rw-aur', rhythm: 'irregular', target: 'rw-aur', cat: ['variable', 'dust'], band: 3, mode: 'epoch', fov: 6,
    desc: { es: 'Una estrella joven con disco que se apaga y enciende sin aviso.', en: 'A young star with a disk that dims and brightens without warning.' } },
  { id: 'mira', rhythm: 'periodic', name: 'Mira (ο Ceti)', query: 'Mira', cat: ['variable'], band: 2, mode: 'epoch', fov: 6,
    desc: { es: 'La primera variable descubierta (1596); pulsa cada 332 días. Tan brillante que satura.', en: 'The first variable star found (1596); pulses every 332 days. So bright it saturates.' } },
  { id: 'chicyg', rhythm: 'periodic', name: 'χ Cygni', query: 'chi Cyg', cat: ['variable'], band: 2, mode: 'epoch', fov: 6,
    desc: { es: 'Una Mira de las que más cambian: miles de veces entre máximo y mínimo en luz visible.', en: 'One of the Miras that changes most: thousands of times between maximum and minimum in visible light.' } },
  { id: 'rleo', rhythm: 'periodic', name: 'R Leonis', query: 'R Leo', cat: ['variable'], band: 2, mode: 'epoch', fov: 6,
    desc: { es: 'Una gigante roja pulsante, de las más fáciles de seguir.', en: 'A pulsating red giant, one of the easiest to follow.' } },
  { id: 'irc10216', name: 'CW Leonis (IRC +10216)', query: 'IRC +10216', cat: ['variable', 'dust'], band: 4, mode: 'epoch', fov: 6,
    desc: { es: 'Una estrella de carbono envuelta en el polvo que expulsa; brilla mucho en el infrarrojo largo.', en: 'A carbon star wrapped in the dust it sheds; very bright in the long infrared.' } },
  { id: 'ttau', rhythm: 'irregular', name: 'T Tauri', query: 'T Tau', cat: ['variable', 'dust'], band: 3, mode: 'epoch', fov: 6,
    desc: { es: 'El prototipo de estrella recién nacida, todavía rodeada de gas y polvo.', en: 'The prototype newborn star, still surrounded by gas and dust.' } },
  { id: 'fuori', rhythm: 'irregular', name: 'FU Orionis', query: 'FU Ori', cat: ['variable', 'dust'], band: 3, mode: 'epoch', fov: 6,
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

// Guided tours of the Learn door. Each step opens an object with a view,
// says what is on screen (`text`), lists what to try (`tasks`, checked off
// by themselves as the user does them) and, once done, what it shows
// (`takeaway`). Each tour ends with a quick question (`quiz`).
//
// Tasks: { do: 'play' } press play and watch a few visits; { do: 'band',
// band } switch to a channel (0-based); { do: 'select' } click the object in
// the middle; { do: 'catalog' } turn on the Gaia/WISE layer. Tours do not
// autoplay, so pressing play is the user's first step.
export const TOURS = [
  {
    id: 'cycle',
    title: { es: 'El ciclo de la materia', en: 'The cycle of matter' },
    summary: {
      es: 'Las estrellas fabrican carbono y oxígeno, lo sueltan como polvo, en el polvo se congelan hielos y de esas nubes nacen estrellas y planetas nuevos.',
      en: 'Stars make carbon and oxygen, shed it as dust, ices freeze on that dust, and new stars and planets are born from those clouds.',
    },
    steps: [
      { object: 'r-dra', view: { band: 2, mode: 'epoch' },
        title: { es: 'Una estrella que suelta su material', en: 'A star shedding its material' },
        text: {
          es: 'En el centro está R Draconis, una gigante roja al final de su vida. Pulsa cada ~245 días y en cada pulso expulsa gas con carbono y oxígeno que ella misma fabricó.',
          en: 'In the middle is R Draconis, a red giant near the end of its life. It pulses every ~245 days, and each pulse throws out gas with carbon and oxygen it made itself.',
        },
        tasks: [{ do: 'play' }, { do: 'select' }],
        takeaway: {
          es: 'Su brillo sube y baja con un ritmo: es el pulso que avienta su material al espacio. Así empieza el ciclo.',
          en: 'Its brightness rises and falls with a rhythm: that pulse throws its material into space. That is where the cycle starts.',
        } },
      { object: 'b68', view: { band: 0, mode: 'epoch' },
        title: { es: 'El material se enfría: polvo y hielo', en: 'The material cools: dust and ice' },
        text: {
          es: 'Barnard 68 es una nube oscura de polvo y gas frío. En el canal 1 tapa casi todas las estrellas que están detrás de ella.',
          en: 'Barnard 68 is a dark cloud of cold dust and gas. In channel 1 it hides almost every star behind it.',
        },
        tasks: [{ do: 'band', band: 5 }],
        takeaway: {
          es: 'En el canal 6 aparecen más estrellas: el infrarrojo largo atraviesa el polvo. Dentro de nubes así, el agua y el CO₂ se congelan sobre los granos de polvo.',
          en: 'In channel 6 more stars appear: long infrared gets through the dust. Inside clouds like this, water and CO₂ freeze onto the dust grains.',
        } },
      { object: 'rw-aur', view: { band: 3, mode: 'epoch' },
        title: { es: 'En las nubes nacen estrellas', en: 'Stars are born in the clouds' },
        text: {
          es: 'RW Aurigae es una estrella joven, todavía rodeada del disco de gas y polvo donde se forman los planetas.',
          en: 'RW Aurigae is a young star, still surrounded by the disk of gas and dust where planets form.',
        },
        tasks: [{ do: 'play' }, { do: 'select' }],
        takeaway: {
          es: 'Parpadea sin un ritmo fijo: su disco la tapa a ratos. De discos así salen los planetas.',
          en: 'It flickers with no fixed rhythm: its disk hides it now and then. Planets come out of disks like this.',
        } },
      { object: 'wise0855', view: { band: 0, mode: 'epoch' },
        title: { es: 'Lo más frío: casi un planeta', en: 'The coldest: almost a planet' },
        text: {
          es: 'En el centro de esta imagen hay una enana marrón, WISE 0855, a unos 0 °C: no tiene masa para encenderse como estrella. En el canal 1 no se ve nada.',
          en: 'In the middle of this image there is a brown dwarf, WISE 0855, at about 0 °C: not massive enough to ignite as a star. In channel 1 you see nothing.',
        },
        tasks: [{ do: 'band', band: 5 }],
        takeaway: {
          es: 'En el canal 6, donde emite su calor, aparece. Su atmósfera tiene agua y metano, como Júpiter. El carbono y el oxígeno de todo esto, y de ti, pasaron por este ciclo.',
          en: 'In channel 6, where it gives off its heat, it appears. Its atmosphere has water and methane, like Jupiter. The carbon and oxygen in all of this, and in you, went through this cycle.',
        } },
    ],
    quiz: {
      q: { es: '¿Por qué en el canal 6 se ven estrellas detrás de Barnard 68?', en: 'Why do stars behind Barnard 68 show up in channel 6?' },
      options: [
        { es: 'Porque el infrarrojo largo atraviesa mejor el polvo', en: 'Because long infrared gets through dust better' },
        { es: 'Porque la nube desaparece con el tiempo', en: 'Because the cloud fades away over time' },
        { es: 'Porque esas estrellas están delante de la nube', en: 'Because those stars are in front of the cloud' },
      ],
      answer: 0,
      explain: {
        es: 'Los granos de polvo son tan pequeños que bloquean la luz de onda corta y dejan pasar la larga. Por eso SPHEREx puede ver dentro de las nubes donde nacen estrellas.',
        en: 'Dust grains are so small that they block short wavelengths and let long ones through. That is why SPHEREx can see inside the clouds where stars are born.',
      },
    },
  },
  {
    id: 'moving',
    title: { es: 'Lo que se mueve', en: 'What moves' },
    summary: {
      es: 'Algunas estrellas cercanas se desplazan tanto que SPHEREx las ve moverse en pocos meses.',
      en: 'Some nearby stars move so much that SPHEREx sees them shift within a few months.',
    },
    steps: [
      { object: 'barnard', view: { band: 1, mode: 'diff', catalog: false },
        title: { es: 'La estrella más rápida', en: 'The fastest star' },
        text: {
          es: 'Esto es el modo Diferencia: cada imagen es la visita actual menos una de referencia (A). Lo que no cambia queda gris. En el centro está la estrella de Barnard.',
          en: 'This is Difference mode: each image is the current visit minus a reference visit (A). Whatever does not change turns gray. Barnard’s Star is in the middle.',
        },
        tasks: [{ do: 'play' }, { do: 'catalog' }],
        takeaway: {
          es: 'Deja un par blanco y negro: blanco donde está ahora, negro donde estaba en la visita A. Avanza 10.4″ por año, y la flecha azul (lo que predice Gaia) apunta justo ahí.',
          en: 'It leaves a white-and-black pair: white where it is now, black where it was at visit A. It moves 10.4″ per year, and the blue arrow (Gaia’s prediction) points right there.',
        } },
      { object: 'eps-indi-b', view: { band: 2, mode: 'diff', catalog: false },
        title: { es: 'Enanas marrones de paseo', en: 'Brown dwarfs on the move' },
        text: {
          es: 'Epsilon Indi B son dos enanas marrones a 12 años luz, en el centro. Se mueven más despacio que Barnard.',
          en: 'Epsilon Indi B is a pair of brown dwarfs 12 light years away, in the middle. They move more slowly than Barnard’s Star.',
        },
        tasks: [{ do: 'play' }, { do: 'select' }],
        takeaway: {
          es: 'Avanzan unos 4.7″ por año hacia el sureste, menos de un píxel: el par blanco y negro es más tenue, pero SPHEREx lo mide.',
          en: 'They move about 4.7″ per year toward the southeast, less than a pixel: the black-and-white pair is fainter, but SPHEREx measures it.',
        } },
      { object: 'wise0855', view: { band: 0, mode: 'diff', catalog: false },
        title: { es: 'Solo se ve en el infrarrojo largo', en: 'Only visible in the long infrared' },
        text: {
          es: 'Aquí se esconde WISE 0855, la enana marrón más fría conocida. En el canal 1 no hay nada que se mueva.',
          en: 'WISE 0855, the coldest known brown dwarf, hides here. In channel 1 nothing moves.',
        },
        tasks: [{ do: 'band', band: 5 }, { do: 'play' }],
        takeaway: {
          es: 'En el canal 6 aparece su par blanco y negro: es tan fría que solo brilla ahí, y aun así se mueve 8.1″ por año hacia el oeste.',
          en: 'In channel 6 its black-and-white pair appears: it is so cold it only shines there, and it still moves 8.1″ per year toward the west.',
        } },
      { object: 'kapteyn', view: { band: 1, mode: 'diff', catalog: true },
        title: { es: 'Una estrella que va a contracorriente', en: 'A star going against the flow' },
        text: {
          es: 'La estrella de Kapteyn es vieja y viene del halo de la galaxia: gira al revés que el Sol.',
          en: 'Kapteyn’s Star is old and comes from the galactic halo: it orbits backwards compared with the Sun.',
        },
        tasks: [{ do: 'play' }, { do: 'select' }],
        takeaway: {
          es: 'Por eso pasa tan rápido a nuestro lado, unos 8.7″ por año. ¿Quieres intentarlo tú? En Descubre hay una misión para encontrar lo que se mueve.',
          en: 'That is why it races past us at about 8.7″ per year. Want to try yourself? The Discover door has a mission to find what moves.',
        } },
    ],
    quiz: {
      q: { es: 'En modo Diferencia, ¿qué significa un par blanco y negro?', en: 'In Difference mode, what does a white-and-black pair mean?' },
      options: [
        { es: 'Una estrella que explotó', en: 'A star that exploded' },
        { es: 'Una estrella que se movió entre dos visitas', en: 'A star that moved between two visits' },
        { es: 'Un error del detector', en: 'A detector glitch' },
      ],
      answer: 1,
      explain: {
        es: 'Blanco es donde está ahora y negro donde estaba en la visita de referencia. Lo que no se mueve se cancela y queda gris.',
        en: 'White is where it is now and black is where it was at the reference visit. Whatever does not move cancels out and turns gray.',
      },
    },
  },
  {
    id: 'variable',
    title: { es: 'Estrellas que cambian', en: 'Stars that change' },
    summary: {
      es: 'Unas estrellas pulsan con un ritmo; otras parpadean sin aviso. SPHEREx las sigue por meses.',
      en: 'Some stars pulse with a rhythm; others flicker without warning. SPHEREx follows them for months.',
    },
    steps: [
      { object: 'r-dra', view: { band: 2, mode: 'epoch' },
        title: { es: 'Una Mira: pulsos de 245 días', en: 'A Mira: 245-day pulses' },
        text: {
          es: 'R Draconis crece y se encoge con un ritmo de 245 días. Al hacer clic sobre una estrella, debajo de la línea de tiempo aparece su curva de luz: el brillo medido en cada visita.',
          en: 'R Draconis swells and shrinks every 245 days. When you click on a star, its light curve, the brightness measured at each visit, appears under the timeline.',
        },
        tasks: [{ do: 'play' }, { do: 'select' }],
        takeaway: {
          es: 'La curva sube y baja como una ola: un pulso con ritmo.',
          en: 'The curve rises and falls like a wave: a pulse with a rhythm.',
        } },
      { object: 'rw-aur', view: { band: 3, mode: 'epoch' },
        title: { es: 'Parpadeo de una estrella joven', en: 'A young star flickering' },
        text: {
          es: 'RW Aurigae no tiene periodo: su disco de polvo la tapa a ratos.',
          en: 'RW Aurigae has no period: its dusty disk hides it now and then.',
        },
        tasks: [{ do: 'play' }, { do: 'select' }],
        takeaway: {
          es: 'Compárala con R Draconis: aquí la curva salta sin ritmo. Así se distinguen las estrellas que pulsan de las que algo tapa.',
          en: 'Compare it with R Draconis: here the curve jumps with no rhythm. That is how stars that pulse are told apart from stars something covers.',
        } },
      { object: 'mira', view: { band: 2, mode: 'epoch' },
        title: { es: 'La primera variable conocida', en: 'The first known variable' },
        text: {
          es: 'Mira fue la primera estrella que se vio cambiar (1596) y pulsa cada 332 días. Es tan brillante que satura el detector.',
          en: 'Mira was the first star seen to change (1596) and pulses every 332 days. It is so bright it saturates the detector.',
        },
        tasks: [{ do: 'play' }],
        takeaway: {
          es: 'El centro sale aplanado porque el detector se llena, pero el halo alrededor crece y se encoge con el pulso.',
          en: 'The core is flattened because the detector fills up, but the halo around it grows and shrinks with the pulse.',
        } },
    ],
    quiz: {
      q: { es: '¿Qué es una curva de luz?', en: 'What is a light curve?' },
      options: [
        { es: 'El camino que recorre una estrella en el cielo', en: 'The path a star takes across the sky' },
        { es: 'Los colores en los que brilla una estrella', en: 'The colors a star shines in' },
        { es: 'El brillo de una estrella medido en cada visita', en: 'A star’s brightness measured at each visit' },
      ],
      answer: 2,
      explain: {
        es: 'Es el brillo contra el tiempo. Si sube y baja con ritmo, la estrella pulsa; si salta sin ritmo, algo la tapa o le cae material. Los colores son el espectro.',
        en: 'It is brightness versus time. If it rises and falls with a rhythm, the star pulses; if it jumps with no rhythm, something covers it or material falls onto it. The colors are the spectrum.',
      },
    },
  },
];

// Missions of the Discover door. Each opens a random object from its pool
// with the name hidden, asks for a few tasks and then checks the answer:
//  - moving: click the star that moves; checked against the Gaia/WISE catalog.
//  - rhythm: read the light curve; the answer is the object's `rhythm`.
//  - temperature: measure the object; the answer comes from the measurements
//    themselves (which part of the infrared it is brightest in).
// `real` adds objects that only exist with real SPHEREx data (looked up in
// Sesame). Bright stars that saturate are left out of `temperature`.
export const MISSIONS = [
  { id: 'moving', icon: '→',
    title: { es: 'Encuentra lo que se mueve', en: 'Find what moves' },
    summary: { es: 'Un campo misterioso en modo Diferencia. Una estrella se mueve: encuéntrala y haz clic en ella.', en: 'A mystery field in Difference mode. One star moves: find it and click on it.' },
    sim: ['barnard', 'eps-indi-b', 'wise0855'],
    real: ['kapteyn', 'groombridge1830', 'wolf359', 'lalande21185', '61cyg', 'proxima', 'luhman16', 'teegarden'],
    view: { mode: 'diff', catalog: false },
    tasks: [{ do: 'play' }, { do: 'select', anywhere: true }] },
  { id: 'rhythm', icon: '∿',
    title: { es: '¿Pulso o parpadeo?', en: 'Pulse or flicker?' },
    summary: { es: 'Una estrella que cambia de brillo. Mide su curva de luz y decide si pulsa con ritmo o parpadea sin él.', en: 'A star that changes brightness. Measure its light curve and decide whether it pulses with a rhythm or flickers without one.' },
    sim: ['r-dra', 'rw-aur'],
    real: ['mira', 'rleo', 'chicyg', 'ttau', 'fuori'],
    view: { mode: 'epoch' },
    tasks: [{ do: 'play' }, { do: 'select' }],
    question: { es: '¿Cómo cambia su brillo?', en: 'How does its brightness change?' },
    options: [
      { id: 'periodic', label: { es: 'Sube y baja con ritmo: pulsa', en: 'Rises and falls with a rhythm: it pulses' } },
      { id: 'irregular', label: { es: 'Salta sin ritmo: parpadea', en: 'Jumps with no rhythm: it flickers' } },
    ] },
  { id: 'temperature', icon: '🌡',
    title: { es: '¿Caliente o frío?', en: 'Hot or cold?' },
    summary: { es: 'Mide en qué color del infrarrojo brilla más un objeto y descubre qué tan caliente es.', en: 'Measure which infrared color an object is brightest in and find out how hot it is.' },
    sim: ['barnard', 'r-dra', 'eps-indi-b', 'wise0855', 'rw-aur'],
    real: ['luhman16', 'teegarden'],
    view: { mode: 'epoch', band: 0 },
    tasks: [{ do: 'band', band: 5 }, { do: 'select' }],
    question: { es: '¿En qué parte del infrarrojo brilla más?', en: 'Which part of the infrared is it brightest in?' },
    options: [
      { id: 'short', label: { es: 'Corto: canales 1–2', en: 'Short: channels 1–2' }, bands: [0, 1] },
      { id: 'mid', label: { es: 'Medio: canales 3–4', en: 'Middle: channels 3–4' }, bands: [2, 3] },
      { id: 'long', label: { es: 'Largo: canales 5–6', en: 'Long: channels 5–6' }, bands: [4, 5] },
    ] },
];

// Spectral features drawn on the spectrum and explained in the band list. They
// come from the server (spherex/features.py, served at /api/features): the
// same table the spectrum analysis uses, so the page keeps no copy of its own.
// Each one is { id, species, label, lo, hi, center, kind: 'abs' | 'emi' |
// 'either', line, desc, confuses }; `l` and `w` are its center and width.
// They fill in when `featuresReady` resolves, without holding up the page.
export const BANDS = [];
export const RULES = [];
export const PSEUDO = {};
export const featuresReady = fetch('/api/features')
  .then((r) => (r.ok ? r.json() : null))
  .catch(() => null)
  .then((j) => {
    if (!j) return false;
    BANDS.push(...j.features.map((f) => ({ ...f, l: f.center, w: f.hi - f.lo })));
    RULES.push(...j.rules);
    Object.assign(PSEUDO, j.pseudo);
    return true;
  });
export const findBand = (id) => BANDS.find((b) => b.id === id);

export const findMission = (id) => MISSIONS.find((m) => m.id === id);
export const findObject = (id) => OBJECTS.find((o) => o.id === id);
