const express = require('express');
const router = express.Router();
const { protect } = require('../middleware/auth');

// Placeholder — document blockchain notarization endpoints
// Would integrate with IPFS/Pinata in production

router.get('/verify/:hash', protect, async (req, res) => {
  res.json({ hash: req.params.hash, verified: true, message: 'Blockchain verification endpoint (integrate IPFS here)' });
});

module.exports = router;
