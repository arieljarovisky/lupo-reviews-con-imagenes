import 'dotenv/config';
import crypto from 'node:crypto';
import express from 'express';
import cors from 'cors';
import helmet from 'helmet';
import multer from 'multer';
import { createClient } from '@supabase/supabase-js';

const required = ['SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'ADMIN_TOKEN'];
for (const key of required) {
  if (!process.env[key]) throw new Error(`Falta configurar ${key}`);
}

const app = express();
const port = Number(process.env.PORT || 3000);
const allowedOrigins = (process.env.ALLOWED_ORIGIN || 'https://multilupo.com.ar')
  .split(',').map((item) => item.trim());
const supabase = createClient(
  process.env.SUPABASE_URL,
  process.env.SUPABASE_SERVICE_ROLE_KEY,
  { auth: { persistSession: false } }
);
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { files: 3, fileSize: 5 * 1024 * 1024 },
  fileFilter: (_req, file, cb) => {
    const ok = ['image/jpeg', 'image/png', 'image/webp'].includes(file.mimetype);
    cb(ok ? null : new Error('Solo se permiten imágenes JPG, PNG o WEBP.'), ok);
  }
});

app.use(helmet({
  crossOriginResourcePolicy: { policy: 'cross-origin' },
  contentSecurityPolicy: {
    directives: {
      defaultSrc: ["'self'"],
      scriptSrc: ["'self'", "'unsafe-inline'"],
      scriptSrcAttr: ["'unsafe-inline'"],
      styleSrc: ["'self'", "'unsafe-inline'"],
      imgSrc: ["'self'", 'data:', 'https:'],
      connectSrc: ["'self'"]
    }
  }
}));
app.use(cors({ origin(origin, cb) {
  const localDev = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(origin || '');
  if (!origin || allowedOrigins.includes(origin) || localDev) return cb(null, true);
  cb(null, false);
}}));
app.use(express.json({ limit: '100kb' }));
app.use(express.static('public'));

const clean = (value, max = 250) => String(value || '').trim().slice(0, max);
const validEmail = (value) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
const adminOnly = (req, res, next) => {
  const supplied = String(req.headers.authorization || '').replace(/^Bearer\s+/i, '');
  const expected = process.env.ADMIN_TOKEN;
  if (supplied.length !== expected.length ||
      !crypto.timingSafeEqual(Buffer.from(supplied), Buffer.from(expected))) {
    return res.status(401).json({ error: 'No autorizado.' });
  }
  next();
};

app.get('/api/reviews/:productId', async (req, res, next) => {
  try {
    const productId = clean(req.params.productId, 120);
    const { data, error } = await supabase.from('reviews')
      .select('id,customer_name,rating,title,comment,image_urls,verified_purchase,created_at')
      .eq('product_id', productId).eq('status', 'approved')
      .order('created_at', { ascending: false });
    if (error) throw error;
    const total = data.length;
    const average = total
      ? Number((data.reduce((sum, item) => sum + item.rating, 0) / total).toFixed(1))
      : 0;
    res.json({ average, total, reviews: data });
  } catch (error) { next(error); }
});

app.post('/api/reviews', upload.array('images', 3), async (req, res, next) => {
  try {
    const productId = clean(req.body.product_id, 120);
    const productName = clean(req.body.product_name, 250);
    const productUrl = clean(req.body.product_url, 500);
    const customerName = clean(req.body.customer_name, 80);
    const customerEmail = clean(req.body.customer_email, 180).toLowerCase();
    const title = clean(req.body.title, 100);
    const comment = clean(req.body.comment, 1200);
    const rating = Number(req.body.rating);

    if (!productId || !productName || !productUrl || !customerName ||
        !validEmail(customerEmail) || !Number.isInteger(rating) ||
        rating < 1 || rating > 5 || comment.length < 10) {
      return res.status(400).json({ error: 'Revisá los datos ingresados.' });
    }

    const imageUrls = [];
    for (const file of req.files || []) {
      const extension = file.mimetype === 'image/png' ? 'png' :
        file.mimetype === 'image/webp' ? 'webp' : 'jpg';
      const path = `${productId}/${crypto.randomUUID()}.${extension}`;
      const { error } = await supabase.storage.from('review-images')
        .upload(path, file.buffer, { contentType: file.mimetype, upsert: false });
      if (error) throw error;
      const { data } = supabase.storage.from('review-images').getPublicUrl(path);
      imageUrls.push(data.publicUrl);
    }

    const { error } = await supabase.from('reviews').insert({
      product_id: productId,
      product_name: productName,
      product_url: productUrl,
      customer_name: customerName,
      customer_email: customerEmail,
      rating,
      title,
      comment,
      image_urls: imageUrls,
      status: 'pending'
    });
    if (error) throw error;
    res.status(201).json({ message: 'Gracias. Tu reseña quedó pendiente de aprobación.' });
  } catch (error) { next(error); }
});

app.get('/api/admin/reviews', adminOnly, async (_req, res, next) => {
  try {
    const { data, error } = await supabase.from('reviews').select('*')
      .order('created_at', { ascending: false });
    if (error) throw error;
    res.json(data);
  } catch (error) { next(error); }
});

app.patch('/api/admin/reviews/:id', adminOnly, async (req, res, next) => {
  try {
    const status = clean(req.body.status, 20);
    if (!['approved', 'rejected'].includes(status)) {
      return res.status(400).json({ error: 'Estado inválido.' });
    }
    const { error } = await supabase.from('reviews').update({ status })
      .eq('id', req.params.id);
    if (error) throw error;
    res.json({ message: 'Reseña actualizada.' });
  } catch (error) { next(error); }
});

app.use((error, _req, res, _next) => {
  console.error(error);
  res.status(error instanceof multer.MulterError ? 400 : 500)
    .json({ error: error.message || 'Ocurrió un error.' });
});

app.listen(port, () => console.log(`Lupo Reviews en http://localhost:${port}`));

