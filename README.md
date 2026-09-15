# Nutrienti — Facturación (Streamlit)

App para cruzar los pedidos capturados por la app de Pedidos Web con la
lista de precios por cliente, guardar el resultado en una Google Sheet, y
generar las facturas en PDF (por cliente, por fecha, o ambos) subiéndolas a
Drive.

## Qué hace

1. **Lee los pedidos** desde la hoja ["Pedidos Web - Registro de
   Solicitudes"](https://docs.google.com/spreadsheets/d/1WKkqvaM27VDxCviwNPWKEI5xKblDH-vgQEi9_5oiQNY)
   (columnas: Fecha Solicitud, Fecha Despacho Deseada, Cliente (texto
   ingresado), Cliente (sugerencia automatica), Similitud (%), Producto,
   Unidad, Cantidad).
2. **Cruza cada línea** contra:
   - La hoja ["RAZONES SOCIALES - NOMBRES
     COMERCIALES"](https://docs.google.com/spreadsheets/d/1_IbW0IhpSxiCVL9Xn97XsIe5wE4AWnWMjG8szdoWSNI)
     (columnas: RAZON SOCIAL, NOMBRE COMERCIAL, ...) — **fuente de verdad**
     para resolver el punto de venta del pedido a su razón social oficial.
     Muchos puntos NO tienen ningún parecido con el nombre de la cadena ni
     con la razón social (ej. "Astoria"/"Bombay"/"Sexy Seoul" son puntos de
     "ALTAS VISTAS SAS"; "Osaki"/"Sorella"/"Caccio y Pepe" son puntos de
     "TAKAMI SA"), así que este mapa se consulta primero.
   - La hoja ["Nutrienti - Precios por Cliente (World
     Office)"](https://docs.google.com/spreadsheets/d/1HMNBT9Qqogz3WgZIenm-jB9wTUP7Ta_NP1BhUhoB3-s)
     (columnas: empresa, codigo, descripcion, unidad, precio) — una vez se
     sabe la razón social del punto, se usa la columna "Lista Precios" del
     cliente en la base de clientes activos para encontrar la "empresa"
     exacta de esta hoja (que a veces es el nombre de la cadena y a veces
     un nombre de marca sin relación con la razón social, ej. "Storia de
     Amore" para la razón social "AMORE GROUP SAS"). Si el punto no está en
     el mapa de razones sociales, se usa como respaldo el comportamiento
     anterior: *fuzzy matching* del texto del pedido contra el nombre de la
     empresa (funciona cuando el punto sí empieza igual que la cadena, ej.
     "la biferia santafe" → "La biferia").
   - `BASE DE DATOS CLIENTES ACTIVOS.xlsx` (subido a Drive, exportado de
     World Office) para traer NIT, dirección, ciudad, teléfono, forma de
     pago y plazo de días de crédito del cliente oficial.
   - Si no se encuentra precio o cliente con suficiente confianza, el campo
     queda como **"no aparece"** (nunca se inventa un valor).
3. **Escribe el resultado** en una Google Sheet nueva llamada "Nutrienti -
   Pedidos con Precios (Facturacion)", dentro de la carpeta "Integracion
   AI" del Drive. Si ya existe (ejecuciones posteriores), la reutiliza y
   sobreescribe con el cruce más reciente — no acumula filas duplicadas.
4. **Genera facturas en PDF**, una por cada combinación cliente + fecha de
   despacho (tal como llegaron agrupados los pedidos), replicando el
   formato de la factura modelo de GRUPO NUTRIENTI S.A.S. Se pueden
   generar filtrando por cliente, por fecha, o por ambos. Cada PDF se sube
   a la carpeta "facturas de prueba" (dentro de "Integracion AI") y también
   se puede descargar directo desde la app.

## Decisiones de negocio ya confirmadas con el usuario

- **Agrupación de cada factura**: cliente + fecha de despacho (una factura
  por cada grupo tal como aparecen en la hoja de pedidos).
- **Fecha de la factura**: la Fecha de Despacho Deseada (día de entrega).
- **Vencimiento**: Fecha + "Plazo Días" del cliente en la base de clientes
  activos; si el cliente no tiene plazo registrado, se asume **30 días**
  por defecto.
- **Numeración (FE ####)**: empieza en `FE 1` y lleva un contador propio,
  guardado en la pestaña `contador_facturas` de la hoja de resultado (no
  está ligado a la numeración oficial de World Office, porque estas son
  facturas de prueba).

## Matching (fuzzy) — cómo funciona y qué tan estricto es

Todo el matching vive en `lib/matching.py` y usa `difflib` (librería
estándar de Python, sin dependencias externas). El cruce (`cross_reference`
en `lib/data.py`) sigue este orden de prioridad para cada línea de pedido:

1. `match_nombre_comercial`: busca el texto del cliente del pedido (texto
   ingresado y sugerencia automática) contra la columna "NOMBRE COMERCIAL"
   de la hoja "RAZONES SOCIALES - NOMBRES COMERCIALES" (umbral 72%). Esta
   es la fuente de verdad — resuelve puntos cuyo nombre no tiene ninguna
   relación con la cadena/razón social.
2. Si se encontró razón social en el paso 1, `find_client_master_by_razon`
   busca esa razón social en la base de clientes activos (ignorando
   sufijos como SAS, S.A., LTDA) y se usa directamente su columna "Lista
   Precios" para identificar la "empresa" exacta de la hoja de precios.
3. Si el punto no está en el mapa, o el cliente no tiene "Lista Precios"
   diligenciada, se usa el comportamiento de respaldo: `match_empresa`
   normaliza texto (sin tildes, minúsculas) y busca la "empresa" de la
   hoja de precios cuyo nombre es prefijo del texto del cliente del pedido
   (ej. "la biferia" es prefijo de "la biferia santafe" → 100% de
   similitud); si no hay prefijo exacto, usa similitud de texto (umbral
   72%). Luego `match_client_master` busca coincidencia exacta contra
   "Lista Precios", o si no la hay, compara la razón social (quitando
   sufijos societarios) contra la empresa encontrada o el texto del
   pedido (umbral 60%).
- `match_product`: compara el nombre de producto del pedido contra las
  descripciones de precio de esa empresa (umbral 78%).

Los umbrales son constantes al inicio de `matching.py` — se pueden ajustar
ahí si el negocio los quiere más estrictos o más flexibles. Cuando ningún
candidato supera el umbral, el campo correspondiente queda en
**"no aparece"** en vez de forzar un match dudoso.

La hoja de resultado incluye dos columnas de transparencia — "Punto (mapa
nombres comerciales)" y "Razon social (mapa)" — que muestran, cuando
aplica, con qué fila del mapa de razones sociales se resolvió cada línea
(quedan en "no aparece" cuando el punto no está en ese mapa y se usó el
respaldo).

> Ejemplos reales verificados con datos de prueba: "astoria santafe" y
> "bombay 127" (sin ningún parecido textual con "Altas Vistas") ahora
> resuelven correctamente a la razón social "ALTAS VISTAS S.A.S" y a la
> empresa de precios "Altas Vistas"; "central cevicheria chia" resuelve a
> "TAKAMI S.A." (antes quedaba en "no aparece" porque "Central cevicheria"
> no es una empresa de la lista de precios — solo aparecía como nombre de
> un producto dentro de la lista de Takami).

## Autenticación con Google

Reutiliza las credenciales OAuth que ya usa la app de pedidos
(`D:\Otros_proyectos\nutrienti\secret.json` / `gsheets_token.json`,
completadas en `.streamlit/secrets.toml` bajo `[gcp_oauth]`). No se usa
cuenta de servicio porque la organización bloquea la creación de llaves de
cuenta de servicio (`iam.disableServiceAccountKeyCreation`).

Los scopes que pide esta app son `spreadsheets` y `drive` completo (no solo
`drive.readonly`), porque necesita:
- descargar `BASE DE DATOS CLIENTES ACTIVOS.xlsx` (archivo Office, no se
  puede leer con la API de Sheets),
- crear la hoja de resultado dentro de una carpeta específica,
- subir los PDF de factura a la carpeta "facturas de prueba".

Si al correr la app aparece un error de permisos de Drive, es porque el
refresh_token reutilizado se autorizó originalmente con un scope más
angosto — en ese caso hay que rehacer el consentimiento OAuth pidiendo
`https://www.googleapis.com/auth/drive` explícitamente.

La hoja "RAZONES SOCIALES - NOMBRES COMERCIALES" la creó
`csanchez@nutrienti.co`; ya está compartida con `contacto@nutrienti.co`
(Editor), que es la cuenta que usa esta app, así que no hace falta ningún
ajuste de permisos. Si en algún momento dejara de estar compartida, la app
lo detecta sola: muestra una advertencia en pantalla y sigue funcionando
con el comportamiento de respaldo (sin el mapa de razones sociales) en vez
de detenerse.

## Instalar y correr localmente

```bash
cd "D:\Otros_proyectos\nutrienti\facturacion\facturacion_repo"
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Desplegar en Streamlit Community Cloud

1. Sube este repo a GitHub (sin `secrets.toml`, ya excluido por
   `.gitignore`).
2. En [share.streamlit.io](https://share.streamlit.io/), conecta el repo y
   selecciona `app.py`.
3. En "Advanced settings" → "Secrets", pega el contenido completo de tu
   `.streamlit/secrets.toml` local.
4. Deploy.

## Estructura del proyecto

```
facturacion_repo/
├── app.py                       # UI de Streamlit (cruce + generacion de PDFs)
├── lib/
│   ├── gauth.py                 # Autenticacion OAuth (gspread + Drive API)
│   ├── data.py                  # Carga de fuentes, cruce, escritura de la hoja, agrupacion
│   ├── matching.py              # Fuzzy matching (cliente/empresa, cliente/base, producto/precio)
│   └── pdf_factura.py           # Generador de PDF (layout, numero a letras, digito NIT)
├── requirements.txt
├── .gitignore
├── .streamlit/
│   ├── config.toml              # Tema visual (colores Nutrienti)
│   ├── secrets.toml             # Credenciales reales (NO se sube a git)
│   └── secrets.toml.example
└── README.md
```

## Pendientes / próximos pasos sugeridos

- Validar con el negocio los casos "no aparece" (clientes o productos sin
  precio conocido) antes de usar las facturas para algo oficial — por eso
  van a la carpeta "facturas de prueba".
- Si en algún momento hace falta más precisión en el matching de nombres de
  cliente, se puede bajar/subir los umbrales en `lib/matching.py`, o
  agregar un mapa manual de excepciones (cliente de pedido → empresa
  exacta) para los casos ambiguos.
- La numeración de factura (`contador_facturas`) es independiente de la
  numeración oficial de World Office; si estas facturas dejan de ser de
  prueba, hay que decidir cómo sincronizar ambos números.
