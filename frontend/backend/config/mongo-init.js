// ── RuPi MongoDB Initialization ──
// This runs automatically when the mongo container first starts

db = db.getSiblingDB('rupi');

// Create collections with validation
db.createCollection('users', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['email'],
      properties: {
        email: { bsonType: 'string', description: 'Email is required' }
      }
    }
  }
});

// Indexes
db.users.createIndex({ email: 1 }, { unique: true });
db.users.createIndex({ googleId: 1 }, { sparse: true });
db.users.createIndex({ createdAt: -1 });

print('✅ RuPi MongoDB initialized successfully');
