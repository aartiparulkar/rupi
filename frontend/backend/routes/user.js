const express = require('express');
const router = express.Router();
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const User = require('../models/User');
const { protect } = require('../middleware/auth');

// ── Multer config (local storage → can swap to GridFS/S3) ──
const uploadDir = path.join(__dirname, '../../uploads');
if (!fs.existsSync(uploadDir)) fs.mkdirSync(uploadDir, { recursive: true });

const storage = multer.diskStorage({
  destination: (req, file, cb) => cb(null, uploadDir),
  filename: (req, file, cb) => {
    const unique = `${req.user._id}-${Date.now()}${path.extname(file.originalname)}`;
    cb(null, unique);
  }
});

const fileFilter = (req, file, cb) => {
  const allowed = ['.pdf', '.jpg', '.jpeg', '.png'];
  const ext = path.extname(file.originalname).toLowerCase();
  if (allowed.includes(ext)) cb(null, true);
  else cb(new Error('Only PDF, JPG, and PNG files are allowed'), false);
};

const upload = multer({
  storage,
  fileFilter,
  limits: { fileSize: 10 * 1024 * 1024 } // 10MB
});

// ── GET /api/user/profile ──
router.get('/profile', protect, async (req, res) => {
  try {
    const user = await User.findById(req.user._id).select('-password');
    if (!user) return res.status(404).json({ message: 'User not found.' });
    res.json({ user: user.toSafeObject() });
  } catch (err) {
    res.status(500).json({ message: 'Error fetching profile.' });
  }
});

// ── PUT /api/user/profile ──
router.put('/profile', protect, async (req, res) => {
  try {
    const allowedFields = [
      'firstName', 'lastName', 'dob', 'gender', 'profession', 'pan',
      'incomeRange', 'taxRegime', 'riskAppetite', 'goals',
      'phone', 'city', 'state', 'address',
      'profileComplete', 'mfaEnabled', 'loginNotifications'
    ];

    const updates = {};
    allowedFields.forEach(field => {
      if (req.body[field] !== undefined) updates[field] = req.body[field];
    });
    updates.updatedAt = new Date();

    const user = await User.findByIdAndUpdate(
      req.user._id,
      { $set: updates },
      { new: true, runValidators: true, select: '-password' }
    );

    res.json({ user: user.toSafeObject(), message: 'Profile updated successfully.' });
  } catch (err) {
    console.error('Profile update error:', err);
    res.status(500).json({ message: 'Error updating profile.' });
  }
});

// ── POST /api/user/documents — upload one or more documents ──
router.post('/documents', protect, upload.array('documents', 10), async (req, res) => {
  try {
    if (!req.files || !req.files.length) {
      return res.status(400).json({ message: 'No files uploaded.' });
    }

    const newDocs = req.files.map(file => ({
      name: file.filename,
      originalName: file.originalname,
      mimeType: file.mimetype,
      size: file.size,
      path: file.path,
      verified: false,
      uploadedAt: new Date()
    }));

    const user = await User.findByIdAndUpdate(
      req.user._id,
      { $push: { documents: { $each: newDocs } } },
      { new: true, select: '-password' }
    );

    res.status(201).json({
      message: `${newDocs.length} document(s) uploaded successfully.`,
      documents: user.documents
    });
  } catch (err) {
    console.error('Document upload error:', err);
    res.status(500).json({ message: 'Error uploading documents.' });
  }
});

// ── GET /api/user/documents ──
router.get('/documents', protect, async (req, res) => {
  try {
    const user = await User.findById(req.user._id).select('documents');
    res.json({ documents: user.documents });
  } catch (err) {
    res.status(500).json({ message: 'Error fetching documents.' });
  }
});

// ── DELETE /api/user/documents/:docId ──
router.delete('/documents/:docId', protect, async (req, res) => {
  try {
    const user = await User.findById(req.user._id);
    const doc = user.documents.id(req.params.docId);
    if (!doc) return res.status(404).json({ message: 'Document not found.' });

    // Remove file from disk
    if (doc.path && fs.existsSync(doc.path)) {
      fs.unlinkSync(doc.path);
    }

    doc.deleteOne();
    await user.save();
    res.json({ message: 'Document deleted successfully.' });
  } catch (err) {
    res.status(500).json({ message: 'Error deleting document.' });
  }
});

module.exports = router;
