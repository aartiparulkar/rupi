const mongoose = require('mongoose');
const bcrypt = require('bcryptjs');

const DocumentSchema = new mongoose.Schema({
  name:        { type: String, required: true },
  originalName:{ type: String },
  mimeType:    { type: String },
  size:        { type: Number },
  path:        { type: String },          // GridFS file ID or local path
  blockchainHash: { type: String },       // IPFS hash for notarization
  verified:    { type: Boolean, default: false },
  uploadedAt:  { type: Date, default: Date.now }
}, { _id: true });

const ChatSessionSchema = new mongoose.Schema({
  agent:      { type: String, enum: ['tax', 'investment', 'security', 'orchestrator'], required: true },
  preview:    { type: String },           // First message snippet
  messages:   [{ role: String, content: String, timestamp: Date }],
  createdAt:  { type: Date, default: Date.now },
  updatedAt:  { type: Date, default: Date.now }
});

const UserSchema = new mongoose.Schema({
  // ── Auth ──
  email:         { type: String, required: true, unique: true, lowercase: true, trim: true },
  password:      { type: String, select: false },    // null for Google-only accounts
  googleId:      { type: String, sparse: true },
  authProvider:  { type: String, enum: ['email', 'google', 'both'], default: 'email' },

  // ── Basic Info ──
  firstName:    { type: String, trim: true },
  lastName:     { type: String, trim: true },
  profileComplete: { type: Boolean, default: false },

  // ── Personal Details ──
  dob:          { type: Date },
  gender:       { type: String },
  profession:   { type: String },
  pan:          { type: String, uppercase: true, trim: true },

  // ── Financial ──
  incomeRange:  { type: String },
  taxRegime:    { type: String, enum: ['new', 'old', ''], default: '' },
  riskAppetite: { type: String, enum: ['conservative', 'moderate', 'aggressive', ''], default: '' },
  goals:        [{ type: String }],

  // ── Contact ──
  phone:        { type: String },
  city:         { type: String },
  state:        { type: String },
  address:      { type: String },           // optional

  // ── Security ──
  mfaEnabled:       { type: Boolean, default: false },
  loginNotifications: { type: Boolean, default: true },
  lastLogin:        { type: Date },

  // ── Data ──
  documents:    [DocumentSchema],
  chatSessions: [ChatSessionSchema],

  createdAt:    { type: Date, default: Date.now },
  updatedAt:    { type: Date, default: Date.now }
});

// ── Pre-save hooks ──
UserSchema.pre('save', async function (next) {
  this.updatedAt = Date.now();
  if (!this.isModified('password') || !this.password) return next();
  this.password = await bcrypt.hash(this.password, 12);
  next();
});

// ── Instance methods ──
UserSchema.methods.comparePassword = async function (candidatePassword) {
  if (!this.password) return false;
  return bcrypt.compare(candidatePassword, this.password);
};

UserSchema.methods.toSafeObject = function () {
  const obj = this.toObject();
  delete obj.password;
  delete obj.__v;
  return obj;
};

// ── Indexes ──
UserSchema.index({ email: 1 });
UserSchema.index({ googleId: 1 }, { sparse: true });

module.exports = mongoose.model('User', UserSchema);
