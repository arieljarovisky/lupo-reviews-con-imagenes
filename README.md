# Lupo Reviews con imágenes

Sistema propio para que los clientes publiquen calificaciones, comentarios y hasta tres fotografías en cada producto de Tiendanube.

## Incluye

- Detección automática del producto actual.
- Promedio y cantidad de reseñas.
- Comentarios con 1 a 5 estrellas.
- Hasta 3 fotos JPG, PNG o WEBP de 5 MB cada una.
- Vista ampliada de las fotografías.
- Moderación antes de publicar.
- Panel privado para aprobar o rechazar.
- Diseño responsive con la identidad visual de Lupo.

## 1. Crear Supabase

1. Creá un proyecto gratuito en Supabase.
2. Abrí **SQL Editor** y ejecutá todo `supabase.sql`.
3. En **Project Settings > API**, copiá:
   - Project URL.
   - `service_role` key. Es privada y nunca debe ir en Tiendanube.

## 2. Configurar el backend

1. Copiá `.env.example` como `.env`.
2. Completá las variables.
3. Usá un `ADMIN_TOKEN` largo y aleatorio.
4. Instalá y probá:

```bash
npm install
npm run dev
```

## 3. Publicar

Subí esta carpeta a un repositorio privado y desplegala como **Web Service en Render**. Usá `npm install` como comando de construcción y `npm start` como comando de inicio. Configurá allí las mismas variables del `.env`.

Si tu URL final es `https://lupo-reviews.onrender.com`, abrí `public/widget.html` y reemplazá:

```js
var API_URL='https://TU-BACKEND.vercel.app';
```

por:

```js
var API_URL='https://lupo-reviews.onrender.com';
```

## 4. Agregarlo a Tiendanube

Pegá el contenido completo de `public/widget.html` en un bloque de código de la plantilla **Producto**, después de la descripción y antes de “Productos similares”. No lo pegues en el CSS global.

## 5. Moderar

Abrí:

```text
https://lupo-reviews.onrender.com/admin.html
```

Ingresá el mismo `ADMIN_TOKEN` configurado en el servidor. Las reseñas nuevas quedan en `pending` y no se muestran hasta que presiones **Aprobar**.

## Seguridad

- No publiques `.env`.
- No pongas `SUPABASE_SERVICE_ROLE_KEY` en Tiendanube.
- Limitá `ALLOWED_ORIGIN` a `https://multilupo.com.ar`.
- Para producción conviene agregar Cloudflare Turnstile y limitación por IP.
- La etiqueta “Compra verificada” queda preparada, pero requiere conectar pedidos mediante la API oficial de Tiendanube.
